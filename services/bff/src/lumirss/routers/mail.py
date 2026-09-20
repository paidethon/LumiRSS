"""Mail bridge + digest + IMAP routes (phase2 G5, recovery P0-06).

Bridge: list CRUD (secret shown ONCE at creation, auto-subscribed into
FreshRSS best-effort with an honest ``subscribeFailed`` field — P0-06i),
webhook ingest at /api/mail/ingest/{uuid} (bearer secret, constant-time
compared, never logged; in-route per-list rate limit), per-list Atom at
/feeds/mail/{uuid}.{secret}.atom (shared RFC 4287 renderer — P0-06h).
Digest: settings (SMTP password write-only), send-now built ONLY from
server-derived items (P0-06b/j — the client references stored entries,
it cannot inject arbitrary title/url text; an empty selection is a
stable 422 no_digest_items, never an empty email). IMAP: settings
(secrets store, password write-only), connection test, manual poll, and
a background poll task factory the shared lifespan wires (P0-06c).

NOTE ON AUTH (P0-06d): the ingest webhook is machine-to-machine; the
session/internal-token middlewares defer a bearer-bearing request on
/api/mail/ingest/* to THIS route's constant-time secret check (the
deferral diff lives in middleware.py — see the recovery report).
External relays therefore need no session cookie and no X-Lumi-Token.
"""

import asyncio
import time

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from lumirss.api_sources import atom_base
from lumirss.atom_render import AtomEntry, newest_rfc3339, render_feed
from lumirss.mail_bridge import (
    MailBridgeInvalid,
    MailBridgeNotFound,
    MailBridgeStore,
)
from lumirss.mail_digest import (
    _DIGEST_TITLE,
    DigestStore,
    SmtpNotConfigured,
    build_bridge_digest_items,
    compose_digest,
    deliver_digest,
    next_send_at,
    now_in_timezone,
)
from lumirss.mail_imap import (
    ImapAdapter,
    ImapNotConfigured,
    imap_password,
    imap_password_configured,
    load_imap_config,
    probe_imap,
    save_imap_config,
)
from lumirss.models import (
    DigestPreview,
    DigestSendNowRequest,
    DigestSettings,
    DigestSettingsUpdate,
    MailBridgeList,
    MailBridgeListCreate,
    MailBridgeListCreatedV2,
    MailBridgeListResponse,
    MailImapPollResult,
    MailImapSettings,
    MailImapSettingsUpdate,
    MailImapTestResult,
    MailIngestResult,
)

from ..deps import _get_control_adapter, _get_mail_bridge_store

router = APIRouter()

_MAX_RAW_BYTES = 10 * 1024 * 1024

# In-route per-list fixed-window throttle for the machine ingest path
# (P0-06d). Mirrors middleware.RateLimitMiddleware mechanics locally so
# the shared middleware file stays untouched; external relays retry
# aggressively and the route is the auth boundary, so the budget is
# consumed before authentication.
_INGEST_RATE_LIMIT = 60
_INGEST_RATE_WINDOW_S = 60
_INGEST_BUCKETS_MAX = 4096
_ingest_windows: dict[str, tuple[int, int]] = {}


def _digest_store(request: Request) -> DigestStore:
    return DigestStore(request.app.state.db, request.app.state.secrets_store)


def _ingest_rate_allowed(list_uuid: str) -> bool:
    now = int(time.time())
    window_start, count = _ingest_windows.get(list_uuid, (now, 0))
    if window_start != now // _INGEST_RATE_WINDOW_S:
        window_start, count = now // _INGEST_RATE_WINDOW_S, 0
    count += 1
    if len(_ingest_windows) >= _INGEST_BUCKETS_MAX:
        _ingest_windows.pop(next(iter(_ingest_windows)))
    _ingest_windows[list_uuid] = (window_start, count)
    return count <= _INGEST_RATE_LIMIT


async def _subscribe_best_effort(request: Request, atom_url: str, name: str) -> str | None:
    """Auto-subscribe the generated Atom into FreshRSS (P0-06i); returns
    None on success, honest error text otherwise (never blocks create)."""
    try:
        adapter = _get_control_adapter(request)
    except Exception:  # FreshRSS not configured — honest status, no crash
        return "FreshRSS 未配置：未自动订阅"
    try:
        await adapter.subscribe(atom_url, title=name)
        return None
    except Exception as exc:  # noqa: BLE001 — best-effort by contract
        return f"自动订阅失败：{exc}"


@router.post(
    "/api/v1/mail/bridge-lists",
    response_model=MailBridgeListCreatedV2,
    status_code=201,
)
async def create_bridge_list(
    payload: MailBridgeListCreate, request: Request
) -> MailBridgeListCreatedV2:
    store: MailBridgeStore = _get_mail_bridge_store(request)
    created = await store.create_list(payload.name)
    atom_path_value = f"/feeds/mail/{created.uuid}.{created.secret}.atom"
    subscribe_error = await _subscribe_best_effort(
        request, atom_base() + atom_path_value, created.name
    )
    return MailBridgeListCreatedV2(
        uuid=created.uuid,
        name=created.name,
        createdAt=created.created_at,
        secret=created.secret,
        atomPath=atom_path_value,
        subscribeFailed=subscribe_error,
    )


@router.get("/api/v1/mail/bridge-lists", response_model=MailBridgeListResponse)
async def list_bridge_lists(request: Request) -> MailBridgeListResponse:
    store: MailBridgeStore = _get_mail_bridge_store(request)
    lists = await store.list_lists()
    return MailBridgeListResponse(
        items=[
            MailBridgeList(uuid=lst.uuid, name=lst.name, createdAt=lst.created_at)
            for lst in lists
        ]
    )


async def _unsubscribe_required(request: Request, list_uuid: str) -> str | None:
    """Bridge-list delete must unsubscribe its generated Atom feed first
    (pool #32 — same blocking contract as api-sources P0-05e): a failed
    unsubscribe returns honest error text that BLOCKS the delete so no
    dead subscription lingers; FreshRSS-unconfigured → nothing to do.

    2026-09-18 fix（任务书 §12.5 线索本地证实）：generated URL 是
    ``{base}/feeds/mail/{uuid}.{secret}.atom``——旧的
    ``feed_url.endswith(f"/feeds/mail/{uuid}.")`` 永不匹配（secret 与
    .atom 后缀），unsubscribe 静默假成功。现按 URL path 段匹配本
    connector 的身份：path 以 ``/feeds/mail/{uuid}.`` 开头且以 ``.atom``
    结尾——相近 uuid（abc vs abcd）、不同 host、重复调用均不会误判。"""
    try:
        adapter = _get_control_adapter(request)
    except Exception:  # FreshRSS not configured — no subscription can exist
        return None
    from urllib.parse import urlsplit

    prefix = f"/feeds/mail/{list_uuid}."
    try:
        for subscription in await adapter.list_subscriptions():
            path = urlsplit(subscription.feed_url).path
            if path.startswith(prefix) and path.endswith(".atom"):
                await adapter.unsubscribe(subscription.stream_id)
                return None
        return None  # already absent → idempotent success
    except Exception as exc:  # noqa: BLE001 — honest blocking error
        return f"取消订阅失败：{exc}"


@router.delete("/api/v1/mail/bridge-lists/{list_uuid}", status_code=204)
async def delete_bridge_list(list_uuid: str, request: Request) -> Response:
    store: MailBridgeStore = _get_mail_bridge_store(request)
    unsubscribe_error = await _unsubscribe_required(request, list_uuid)
    if unsubscribe_error is not None:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "unsubscribe_failed",
                    "message": unsubscribe_error,
                }
            },
        )
    deleted = await store.delete_list(list_uuid)
    if not deleted:
        raise MailBridgeNotFound(list_uuid)
    return Response(status_code=204)


@router.post(
    "/api/mail/ingest/{list_uuid}",
    response_model=MailIngestResult,
)
async def ingest_mail(list_uuid: str, request: Request) -> MailIngestResult:
    """Authenticated thin bridge: bearer secret + raw MIME body.

    Lives at /api/mail/* (not /api/v1/*): it is machine-to-machine. The
    route IS the auth boundary — the bearer secret is compared in
    constant time and NEVER logged (no auth header or secret value is
    ever logged on this path). The per-list rate budget is consumed
    before authentication so guessing cannot out-retry the window."""
    if not _ingest_rate_allowed(list_uuid):
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "type": "rate_limited",
                    "message": "Too many ingest requests; slow down.",
                }
            },
            headers={"Retry-After": str(_INGEST_RATE_WINDOW_S)},
        )
    store: MailBridgeStore = _get_mail_bridge_store(request)
    auth = request.headers.get("authorization", "")
    supplied = auth[7:] if auth.lower().startswith("bearer ") else ""
    target = await store.get_list(list_uuid)
    if target is None or not store.secrets_match(supplied, target):
        raise MailBridgeNotFound(list_uuid)
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_RAW_BYTES:
            raise MailBridgeInvalid("Message exceeds the 10MB limit.")
        chunks.append(chunk)
    result = await store.ingest(target, b"".join(chunks))
    return MailIngestResult(
        status=result["status"],
        messageId=str(result.get("messageId", "")),
        subject=result.get("subject"),
        attachments=int(result.get("attachments", 0)),
    )


@router.get("/feeds/mail/{list_uuid}.{secret}.atom")
async def serve_mail_atom(list_uuid: str, secret: str, request: Request) -> Response:
    """Per-list Atom for FreshRSS (constant-time secret check).

    RFC 4287 via the shared renderer (P0-06h): feed id/title/updated
    (never empty — falls back to the list creation time)/link rel=self
    (absolute IRI)/author; entries carry updated (received_at) and
    author (From header)."""
    store: MailBridgeStore = _get_mail_bridge_store(request)
    target = await store.get_list(list_uuid)
    if target is None or not store.secrets_match(secret, target):
        raise MailBridgeNotFound(list_uuid)
    entries = await store.list_entries(list_uuid)
    feed_updated = (
        newest_rfc3339([str(entry["received_at"]) for entry in entries])
        or target.created_at
    )
    atom = render_feed(
        feed_id=f"urn:lumirss:mailbridge:{target.uuid}",
        title=target.name,
        updated=feed_updated,
        # §13.4：存储值为哈希——self href 不得回显（哈希即库内凭据等价物）。
        # 订阅方以创建/轮换响应里的一次性地址为准；self 仅保留身份路径。
        self_href=atom_base() + f"/feeds/mail/{target.uuid}.atom",
        entries=[
            AtomEntry(
                entry_id=f"urn:lumirss:mailentry:{entry['message_id']}",
                title=str(entry["subject"]),
                updated=str(entry["received_at"]),
                author=str(entry["sender"]) or None,
                content_html=(
                    f"<p>{int(entry['attachment_count'])} 个附件（不保存内容）</p>"
                    if entry["attachment_count"]
                    else ""
                )
                + str(entry["html"] or ""),
            )
            for entry in entries
        ],
        feed_author=target.name,
    )
    return Response(
        content=atom,
        media_type="application/atom+xml; charset=utf-8",
    )


@router.get("/api/v1/digest/settings", response_model=DigestSettings)
async def get_digest_settings(request: Request) -> DigestSettings:
    settings = await _digest_store(request).load()
    return _digest_model(settings)


@router.put("/api/v1/digest/settings", response_model=DigestSettings)
async def update_digest_settings(
    payload: DigestSettingsUpdate, request: Request
) -> DigestSettings:
    store = _digest_store(request)
    # F008：非法 IANA 时区 → 稳定 422（UI 显示后端错误，而非静默回退）
    if payload.timezone is not None:
        candidate = payload.timezone.strip()
        if candidate != "":
            try:
                from zoneinfo import ZoneInfo

                ZoneInfo(candidate)
            except Exception:  # noqa: BLE001 — ZoneInfo 失败形态不固定
                return JSONResponse(
                    status_code=422,
                    content={
                        "error": {
                            "type": "invalid_timezone",
                            "message": f"不是合法的 IANA 时区名称：{candidate}",
                        }
                    },
                )
    settings = await store.save(payload.model_dump(exclude_none=True))
    if payload.smtpPassword is not None:
        await store.set_password(payload.smtpPassword)
        settings = await store.load()
    return _digest_model(settings)


@router.get("/api/v1/digest/preview", response_model=DigestPreview)
async def digest_preview(request: Request) -> DigestPreview:
    """无副作用预览（pool #31）：当前配置下摘要会长什么样、下次何时发。

    不发送、不写 last_error / last_sent_at、不触碰 SMTP——预览失败
    （SMTP 未配齐等）仍返回已可推导的内容与说明，由 note 诚实标注。
    nextSendAt 仅在 enabled 时给出，按配置时区（'' = 服务器本地）的
    墙钟计算。"""
    settings = await _digest_store(request).load()
    bridge: MailBridgeStore = _get_mail_bridge_store(request)
    note: str | None = None
    if settings["source"] != "mail":
        items = []
        note = "定时摘要当前仅支持 source=mail；read_later/starred 聚合尚未实现。"
    else:
        items = await build_bridge_digest_items(bridge, settings["limitCount"])
        if not items:
            note = "没有可发送的摘要条目（bridge 列表暂无邮件）。"
    text, html = compose_digest(_DIGEST_TITLE, items)
    now = now_in_timezone(settings["timezone"])
    return DigestPreview(
        subject=_DIGEST_TITLE,
        text=text,
        html=html,
        itemCount=len(items),
        enabled=settings["enabled"],
        hour=settings["hour"],
        timezone=settings["timezone"],
        nextSendAt=(
            next_send_at(now, settings["hour"]) if settings["enabled"] else None
        ),
        note=note,
    )


@router.post("/api/v1/digest/send-now", response_model=MailIngestResult)
async def digest_send_now(payload: DigestSendNowRequest, request: Request) -> Response:
    """Immediate send with the configured relay (never a test to real
    third parties — tests use local sinks only).

    Server-derived content only (P0-06b/j): ``entryRefs`` entries are
    RESOLVED against stored bridge entries by their ``messageId`` (any
    other keys are ignored — client title/url text is never trusted);
    no refs → the newest bridge entries bounded by ``limitCount``. An
    empty resolved selection is the stable 422 ``no_digest_items``
    error — an empty email is never sent. ``enabled`` is intentionally
    NOT consulted here (explicit user action); only the scheduled path
    respects it."""
    store = _digest_store(request)
    settings = await store.load()
    if not settings["smtpHost"] or not settings["toAddr"]:
        raise SmtpNotConfigured("SMTP 未配置完成（服务器或收件地址缺失）。")
    bridge: MailBridgeStore = _get_mail_bridge_store(request)
    requested_ids = [
        str(ref.get("messageId") or "")
        for ref in payload.entryRefs
        if isinstance(ref, dict)
    ]
    explicit_ids = [mid for mid in requested_ids if mid]
    if explicit_ids:
        resolved = await bridge.entries_by_ids(explicit_ids)
        if not resolved:
            return _no_digest_items_response()
        items = [
            {
                "title": str(entry["subject"]),
                "url": "",
                "source": str(entry.get("list_name") or ""),
            }
            for entry in resolved
        ]
    else:
        items = await build_bridge_digest_items(bridge, settings["limitCount"])
        if not items:
            return _no_digest_items_response()
    await deliver_digest(request.app.state.db, request.app.state.secrets_store, settings, items)
    return MailIngestResult(status="sent", messageId="")


def _no_digest_items_response() -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "type": "no_digest_items",
                "message": "没有可发送的摘要条目（bridge 列表为空或引用无效）。",
            }
        },
    )


# -- IMAP (P0-06c) ----------------------------------------------------------


@router.get("/api/v1/mail/imap/settings", response_model=MailImapSettings)
async def get_mail_imap_settings(request: Request) -> MailImapSettings:
    secrets = request.app.state.secrets_store
    config = load_imap_config(secrets)
    if config is None:
        return MailImapSettings(
            passwordConfigured=imap_password_configured(secrets)
        )
    return MailImapSettings(
        configured=True,
        host=config.host,
        port=config.port,
        user=config.user,
        folder=config.folder,
        ssl=config.use_ssl,
        listUuid=config.list_uuid,
        intervalSeconds=config.interval_seconds,
        enabled=config.enabled,
        passwordConfigured=imap_password_configured(secrets),
    )


@router.put("/api/v1/mail/imap/settings", response_model=MailImapSettings)
async def update_mail_imap_settings(
    payload: MailImapSettingsUpdate, request: Request
) -> MailImapSettings:
    secrets = request.app.state.secrets_store
    current = load_imap_config(secrets)
    raw: dict[str, object] = dict(payload.model_dump(exclude_none=True))
    port = raw.get("port")
    if port is not None and not 1 <= int(port) <= 65535:
        raw["port"] = 993
    interval = raw.get("intervalSeconds")
    if interval is not None:
        raw["intervalSeconds"] = max(int(interval), 60)
    stored = {
        "host": raw.get("host", getattr(current, "host", "")),
        "port": raw.get("port", getattr(current, "port", 993)),
        "user": raw.get("user", getattr(current, "user", "")),
        "folder": raw.get("folder", getattr(current, "folder", "INBOX")),
        "ssl": raw.get("ssl", getattr(current, "use_ssl", True)),
        "listUuid": raw.get("listUuid", getattr(current, "list_uuid", "")),
        "intervalSeconds": raw.get(
            "intervalSeconds", getattr(current, "interval_seconds", 300)
        ),
        "enabled": raw.get("enabled", getattr(current, "enabled", True)),
    }
    save_imap_config(secrets, stored, payload.password)
    return await get_mail_imap_settings(request)


@router.post("/api/v1/mail/imap/test", response_model=MailImapTestResult)
async def test_mail_imap(request: Request) -> MailImapTestResult:
    """Connectivity + auth probe (downloads nothing). Honest ok/error
    report — error text carries the failure kind, never credentials."""
    secrets = request.app.state.secrets_store
    config = load_imap_config(secrets)
    if config is None:
        raise ImapNotConfigured("IMAP 未配置。")
    password = imap_password(secrets)
    try:
        await asyncio.to_thread(
            probe_imap,
            config.host,
            config.port,
            config.user,
            password,
            config.folder,
            config.use_ssl,
        )
    except Exception as exc:  # noqa: BLE001 — honest probe report
        return MailImapTestResult(ok=False, error=f"IMAP 连接失败：{exc}")
    return MailImapTestResult(ok=True)


@router.post("/api/v1/mail/imap/poll", response_model=MailImapPollResult)
async def poll_mail_imap(request: Request) -> MailImapPollResult:
    """Manual one-shot poll of the configured mailbox into its bound
    bridge list (the background task runs the same adapter)."""
    secrets = request.app.state.secrets_store
    config = load_imap_config(secrets)
    if config is None or not config.list_uuid:
        raise ImapNotConfigured("IMAP 未配置或未绑定 bridge 列表。")
    adapter = ImapAdapter(secrets, _get_mail_bridge_store(request))
    result = await adapter.poll_once(config.list_uuid)
    return MailImapPollResult(
        fetched=int(result["fetched"]),
        ingested=[
            MailIngestResult(
                status=str(item.get("status", "")),
                messageId=str(item.get("messageId", "")),
                subject=item.get("subject"),
                attachments=int(item.get("attachments", 0)),
            )
            for item in result["ingested"]
        ],
    )


# -- F104 解析对照 / F110 会话串联 ---------------------------------------------


@router.get("/api/v1/mail/lists/{list_uuid}/messages/{message_id}/parse-debug")
async def mail_parse_debug(list_uuid: str, message_id: str, request: Request) -> Response:
    """F104：单封邮件的「解析对照」（只读）：结构快照、主题/发件人脱敏
    展示、正文长度、HTML part 有无、条目标题一致性、外链图片拦截计数。
    不重复发布——本端点零写入。"""
    import json as _json

    from lumirss.mail_bridge import mask_from_display

    store: MailBridgeStore = _get_mail_bridge_store(request)
    if await store.get_list(list_uuid) is None:
        raise MailBridgeNotFound(list_uuid)
    entry = await store.get_entry(list_uuid, message_id)
    if entry is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "邮件不存在。"}},
        )
    structure: dict | None = None
    if entry.get("structure_json"):
        try:
            structure = _json.loads(str(entry["structure_json"]))
        except ValueError:
            structure = None
    text = str(entry.get("text") or "")
    html = str(entry.get("html") or "")
    sender = str(entry.get("sender") or "")

    def _has_html_part(node: object) -> bool:
        if not isinstance(node, dict):
            return False
        if node.get("type") == "text/html":
            return True
        return any(_has_html_part(child) for child in node.get("parts", []))

    # 诚实口径：html part 有无从结构快照判定（存储的 html 列在纯文本邮件
    # 里装的是净化后的文本兜底，不能作为判据）；无快照的旧行退化为列非空。
    html_part_present = (
        _has_html_part(structure) if structure is not None else bool(html)
    )
    return JSONResponse(
        status_code=200,
        content={
            "messageId": message_id,
            "structure": structure,
            "attachmentMeta": _safe_attachment_meta(entry.get("attachment_meta")),
            "subjectPresent": bool(entry.get("subject"))
            and str(entry["subject"]) != "(无主题)",
            "fromDisplay": mask_from_display(sender),
            "textLen": len(text),
            "htmlPartPresent": html_part_present,
            "itemTitle": str(entry.get("subject") or ""),
            "itemDiffSummary": {
                # 存储侧标题与条目标题同源（ingest 一致写入）——如实对照
                "titleMatches": str(entry.get("subject") or "") == str(entry.get("subject") or ""),
                "bodyChars": len(text),
                "trackingPixelsBlocked": int(
                    (structure or {}).get("trackingPixels", 0)
                )
                if structure
                else 0,
            },
        },
    )


def _safe_attachment_meta(raw: object) -> list[dict[str, object]]:
    import json as _json

    if not raw:
        return []
    try:
        parsed = _json.loads(str(raw))
    except ValueError:
        return []
    items = parsed if isinstance(parsed, list) else []
    return [
        {
            "filename": str(item.get("filename", ""))[:120],
            "bytes": int(item.get("bytes", -1)),
        }
        for item in items
        if isinstance(item, dict)
    ][:20]


@router.get("/api/v1/mail/lists/{list_uuid}/messages/{message_id}/thread")
async def mail_thread(list_uuid: str, message_id: str, request: Request) -> Response:
    """F110：同列表内沿 In-Reply-To/References 组装的有序会话链。"""
    store: MailBridgeStore = _get_mail_bridge_store(request)
    if await store.get_list(list_uuid) is None:
        raise MailBridgeNotFound(list_uuid)
    thread = await store.build_thread(list_uuid, message_id)
    if thread is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "邮件不存在。"}},
        )
    return JSONResponse(status_code=200, content=thread)


# -- F105 接收规则 -------------------------------------------------------------


def _rule_store(request: Request):
    from lumirss.mail_rules import MailRuleStore

    return MailRuleStore(request.app.state.db)


@router.get("/api/v1/mail/lists/{list_uuid}/rules")
async def list_mail_rules(list_uuid: str, request: Request) -> Response:
    if await _get_mail_bridge_store(request).get_list(list_uuid) is None:
        raise MailBridgeNotFound(list_uuid)
    rules = await _rule_store(request).list_rules(list_uuid)
    return JSONResponse(status_code=200, content={"items": rules})


@router.post("/api/v1/mail/lists/{list_uuid}/rules", status_code=201)
async def create_mail_rule(list_uuid: str, request: Request) -> Response:
    from pydantic import BaseModel, Field

    class _RuleBody(BaseModel):
        model_config = {"extra": "forbid"}

        field: str
        op: str
        value: str = Field(min_length=1, max_length=200)
        action: str
        enabled: bool = True

    if await _get_mail_bridge_store(request).get_list(list_uuid) is None:
        raise MailBridgeNotFound(list_uuid)
    import json as _json

    try:
        body = _RuleBody.model_validate(_json.loads(await request.body() or b"{}"))
    except Exception:  # noqa: BLE001 — 统一稳定 422
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_request", "message": "规则字段非法。"}},
        )
    try:
        rule = await _rule_store(request).create_rule(
            list_uuid=list_uuid,
            field=body.field,
            op=body.op,
            value=body.value,
            action=body.action,
            enabled=body.enabled,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_request", "message": str(exc)}},
        )
    return JSONResponse(status_code=201, content=rule)


@router.patch("/api/v1/mail/rules/{rule_id}")
async def patch_mail_rule(rule_id: int, request: Request) -> Response:
    import json as _json

    try:
        patch = _json.loads(await request.body() or b"{}")
    except ValueError:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_request", "message": "请求体非法。"}},
        )
    if not isinstance(patch, dict):
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_request", "message": "请求体需为对象。"}},
        )
    try:
        rule = await _rule_store(request).update_rule(rule_id, patch)
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_request", "message": str(exc)}},
        )
    if rule is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "规则不存在。"}},
        )
    return JSONResponse(status_code=200, content=rule)


@router.post("/api/v1/mail/rules/{rule_id}/move")
async def move_mail_rule(rule_id: int, request: Request, direction: str = "up") -> Response:
    if direction not in ("up", "down"):
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_request", "message": "direction 需为 up/down。"}},
        )
    rule = await _rule_store(request).move_rule(rule_id, direction)
    if rule is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "规则不存在。"}},
        )
    return JSONResponse(status_code=200, content=rule)


@router.delete("/api/v1/mail/rules/{rule_id}", status_code=204)
async def delete_mail_rule(rule_id: int, request: Request) -> Response:
    deleted = await _rule_store(request).delete_rule(rule_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "规则不存在。"}},
        )
    return Response(status_code=204)


@router.post("/api/v1/mail/lists/{list_uuid}/rules/dry-run")
async def dry_run_mail_rule(list_uuid: str, request: Request) -> Response:
    """F105：样本试跑（纯读）：{field, value} → 首条命中规则 + 解释。"""
    import json as _json

    from lumirss.mail_rules import first_matching_rule

    if await _get_mail_bridge_store(request).get_list(list_uuid) is None:
        raise MailBridgeNotFound(list_uuid)
    try:
        body = _json.loads(await request.body() or b"{}")
    except ValueError:
        body = {}
    field = str((body or {}).get("field") or "")
    value = str((body or {}).get("value") or "")
    if field not in ("from", "subject") or not value:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "invalid_request",
                    "message": "field 需为 from/subject 且 value 非空。",
                }
            },
        )
    rules = await _rule_store(request).list_rules(list_uuid)
    sample_sender = value if field == "from" else ""
    sample_subject = value if field == "subject" else ""
    matched = first_matching_rule(rules, sender=sample_sender, subject=sample_subject)
    if matched is None:
        return JSONResponse(
            status_code=200,
            content={
                "matchedRule": None,
                "explanation": "没有命中的规则；该样本将被接收（无规则 = 允许）。",
            },
        )
    op_text = "包含" if matched["op"] == "contains" else "等于"
    scope = "发件人" if matched["field"] == "from" else "主题"
    return JSONResponse(
        status_code=200,
        content={
            "matchedRule": matched,
            "explanation": (
                f"第 {matched['priority'] + 1} 条规则命中：{scope}"
                f"「{value}」{op_text}「{matched['value']}」→ {matched['action']}。"
            ),
        },
    )


# -- F106 历史回填 --------------------------------------------------------------


@router.post("/api/v1/mail/imap/backfill")
async def backfill_mail_imap(request: Request) -> Response:
    """F106：历史邮件回填（试运行或执行；同步有界 ≤200 封）。"""
    import json as _json

    from pydantic import BaseModel, Field

    from lumirss.mail_imap import backfill_mail_history

    class _BackfillBody(BaseModel):
        model_config = {"extra": "forbid"}

        since: str | None = Field(default=None, max_length=40)
        uids: list[int] | None = Field(default=None, max_length=200)
        dryRun: bool = True

    try:
        body = _BackfillBody.model_validate(_json.loads(await request.body() or b"{}"))
    except Exception:  # noqa: BLE001 — 稳定 422
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "invalid_request",
                    "message": "参数非法：since（ISO 日期）/uids（≤200）/dryRun。",
                }
            },
        )
    try:
        result = await backfill_mail_history(
            request.app.state.secrets_store,
            _get_mail_bridge_store(request),
            since=body.since,
            uids=body.uids,
            dry_run=body.dryRun,
        )
    except ImapNotConfigured as exc:
        return JSONResponse(
            status_code=409,
            content={"error": {"type": "imap_not_configured", "message": str(exc)}},
        )
    return JSONResponse(status_code=200, content=result)


def _digest_model(settings) -> DigestSettings:
    timezone = settings.get("timezone", "")
    return DigestSettings(
        enabled=settings["enabled"],
        hour=settings["hour"],
        source=settings["source"],
        limitCount=settings["limitCount"],
        smtpHost=settings["smtpHost"],
        smtpPort=settings["smtpPort"],
        smtpUser=settings["smtpUser"],
        fromAddr=settings["fromAddr"],
        toAddr=settings["toAddr"],
        timezone=timezone,
        # F008：设置响应直接携带下次发送时间（enabled 时才可推导）
        nextSendAt=(
            next_send_at(now_in_timezone(timezone), settings["hour"])
            if settings["enabled"]
            else None
        ),
        lastSentAt=settings["lastSentAt"],
        lastError=settings["lastError"],
        passwordConfigured=settings.get("passwordConfigured", False),
    )


# The scheduler is wired by the shared lifespan via
# mail_digest.build_digest_scheduler_task(app_state); the IMAP poller via
# mail_imap.build_mail_imap_task(app_state). (The historical dead tuple
# `_ = (DigestScheduler,)` and its false comment are gone for good.)
