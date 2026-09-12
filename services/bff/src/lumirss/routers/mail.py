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
    DigestStore,
    SmtpNotConfigured,
    build_bridge_digest_items,
    deliver_digest,
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


@router.delete("/api/v1/mail/bridge-lists/{list_uuid}", status_code=204)
async def delete_bridge_list(list_uuid: str, request: Request) -> Response:
    store: MailBridgeStore = _get_mail_bridge_store(request)
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
        self_href=atom_base() + f"/feeds/mail/{target.uuid}.{target.secret}.atom",
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
    settings = await store.save(payload.model_dump(exclude_none=True))
    if payload.smtpPassword is not None:
        await store.set_password(payload.smtpPassword)
        settings = await store.load()
    return _digest_model(settings)


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


def _digest_model(settings) -> DigestSettings:
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
        lastSentAt=settings["lastSentAt"],
        lastError=settings["lastError"],
        passwordConfigured=settings.get("passwordConfigured", False),
    )


# The scheduler is wired by the shared lifespan via
# mail_digest.build_digest_scheduler_task(app_state); the IMAP poller via
# mail_imap.build_mail_imap_task(app_state). (The historical dead tuple
# `_ = (DigestScheduler,)` and its false comment are gone for good.)
