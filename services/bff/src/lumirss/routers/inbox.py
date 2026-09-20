"""Inbox push sources (0021).

Two audiences, one router:

- user routes (session): manage connectors and read what they pushed —
  GET /api/v1/inbox/sources, POST /api/v1/inbox/sources,
  DELETE /api/v1/inbox/sources/{uuid}, GET /api/v1/inbox/items,
  DELETE /api/v1/inbox/items/{uuid};
- machine route (bearer): POST /api/v1/inbox/ingest/{uuid} — external
  scripts/agents push JSON items that become Lumi-owned ``api_item``
  content (ADR 0004). The route IS the auth boundary: the per-source
  bearer secret is compared in constant time and NEVER logged, mirroring
  the mail bridge ingest. The two auth middlewares defer bearer-bearing
  requests on this prefix (see middleware.py).

Everything pushed is untrusted input: unknown fields are rejected,
HTML is sanitized server-side before storage, and the final render
boundary stays DOMPurify in the browser.
"""

import base64
import contextlib
import json
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from lumirss.cursor import InvalidCursor
from lumirss.errors import InvalidInboxPayload
from lumirss.inbox_rules import (
    InboxRuleNotFound,
    InboxRuleStore,
    first_matching_rule,
)
from lumirss.inbox_store import (
    InboxItemNotFound,
    InboxSourceNotFound,
    InboxStore,
)
from lumirss.models import (
    InboxIngestItem,
    InboxIngestResult,
    InboxItemList,
    InboxItemRow,
    InboxRule,
    InboxRuleCreate,
    InboxRuleDryRun,
    InboxRuleDryRunResult,
    InboxRuleList,
    InboxRuleUpdate,
    InboxSource,
    InboxSourceCreate,
    InboxSourceCreated,
)

from ..deps import _get_inbox_store, _get_workspace_store, _rag_mark_stale

router = APIRouter()

_DEFAULT_LIMIT = 20
_MAX_CATEGORIES = 24
_MAX_CATEGORY_LENGTH = 64
_CURSOR_PREFIX = "inbox1."
_MAX_CURSOR_LENGTH = 512


class _TextSink(HTMLParser):
    """Collect text out of already-sanitized HTML (stdlib parser)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self._parts).split())


def _html_to_text(html: str) -> str:
    sink = _TextSink()
    try:
        sink.feed(html)
    except Exception:  # noqa: BLE001 — text derivation must never 500
        return ""
    return sink.text()


def _validate_optional_url(url: str | None) -> str | None:
    """Inbox URLs are stored for display/open, never fetched server-side —
    only a scheme+host sanity check applies (no javascript: links)."""
    if url is None:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise InvalidInboxPayload("url must be an absolute http(s) URL.")
    return url


def _validate_published_at(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidInboxPayload(
            "publishedAt must be an ISO-8601 timestamp."
        ) from exc
    return value


_MAX_NESTING_DEPTH = 4


def _raw_depth(value: object, depth: int = 0) -> int:
    if not isinstance(value, dict):
        return depth
    return max(
        [_raw_depth(child, depth + 1) for child in value.values()] or [depth]
    )


def prepare_ingest_item(item: InboxIngestItem) -> dict[str, Any]:
    """F108 共享校验/净化工：正式 ingest 与 dry-run 走同一函数——契约
    试跑结果与真实投递行为一致（两路一致由单测保证）。返回 prepared
    值 dict；校验失败抛 InvalidInboxPayload。HTML 在此净化（危险标记
    不可能进入 would_create/storage）。"""
    url = _validate_optional_url(item.url)
    published_at = _validate_published_at(item.publishedAt)
    content_html = ""
    content_text = (item.content or "").strip()
    if item.contentHtml:
        from lumirss.article_sanitize import sanitize_html

        content_html = sanitize_html(item.contentHtml)
        if not content_text:
            content_text = _html_to_text(content_html)
    title = (item.title or item.guid).strip()[:512]
    return {
        "guid": item.guid.strip(),
        "title": title,
        "url": url,
        "author": (item.author or "").strip() or None,
        "content_html": content_html,
        "content_text": content_text[:200_000],
        "published_at": published_at,
        "categories": _clean_categories(item.categories),
    }


def _clean_categories(categories: list[str]) -> list[str]:
    cleaned: list[str] = []
    for raw in categories[:_MAX_CATEGORIES]:
        item = raw.strip()[:_MAX_CATEGORY_LENGTH]
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned


def _encode_cursor(created_at: str, item_uuid: str) -> str:
    payload = json.dumps({"k": created_at, "u": item_uuid}).encode()
    return _CURSOR_PREFIX + base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        raw = cursor.removeprefix(_CURSOR_PREFIX)
        padded = raw + "=" * (-len(raw) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return str(data["k"]), str(data["u"])
    except Exception as exc:
        raise InvalidCursor("Invalid inbox cursor.") from exc


@router.post("/api/v1/inbox/sources", response_model=InboxSourceCreated)
async def create_inbox_source(
    request: Request, body: InboxSourceCreate
) -> InboxSourceCreated:
    """Create an inbox connector. The bearer secret is returned exactly
    once; it cannot be retrieved afterwards."""
    store = _get_inbox_store(request)
    created = await store.create_source(body.name.strip())
    return InboxSourceCreated(
        uuid=created["uuid"],
        name=created["name"],
        secret=created["secret"],
        ingestPath=f"/api/v1/inbox/ingest/{created['uuid']}",
        createdAt=created["createdAt"],
    )


@router.get("/api/v1/inbox/sources", response_model=list[InboxSource])
async def list_inbox_sources(request: Request) -> list[InboxSource]:
    store = _get_inbox_store(request)
    rows = await store.list_sources()
    return [
        InboxSource(
            uuid=row["uuid"],
            name=row["name"],
            enabled=row["enabled"],
            lastSuccessAt=row["lastSuccessAt"],
            lastError=row["lastError"],
            createdAt=row["createdAt"],
        )
        for row in rows
    ]


@router.post("/api/v1/inbox/sources/{source_uuid}/rotate", response_model=InboxSourceCreated)
async def rotate_inbox_source_secret(
    request: Request, source_uuid: str
) -> InboxSourceCreated:
    """Rotate the bearer secret (pool #28). The old token fails from the
    next request on; pushed items are untouched; the new secret is shown
    exactly once, like creation. Rotation never bypasses the Caddy/app
    auth boundary."""
    store = _get_inbox_store(request)
    source = await store.get_source(source_uuid)
    secret = await store.rotate_secret(source_uuid)
    if source is None or secret is None:
        raise InboxSourceNotFound(source_uuid)
    return InboxSourceCreated(
        uuid=source["uuid"],
        name=source["name"],
        secret=secret,
        ingestPath=f"/api/v1/inbox/ingest/{source_uuid}",
        createdAt=source["createdAt"],
    )


@router.delete("/api/v1/inbox/sources/{source_uuid}")
async def delete_inbox_source(request: Request, source_uuid: str) -> dict:
    """Delete a connector and every item it pushed (identity, payload and
    search projections in one operation; RAG invalidation best-effort)."""
    store = _get_inbox_store(request)
    deleted_refs = await store.delete_source(source_uuid)
    if deleted_refs is None:
        raise InboxSourceNotFound(source_uuid)
    if deleted_refs:
        await _rag_mark_stale(request, deleted_refs)
    return {"deleted": True, "items": len(deleted_refs)}


@router.post("/api/v1/inbox/ingest/{source_uuid}", response_model=InboxIngestResult)
async def ingest_inbox_item(
    source_uuid: str, request: Request, item: InboxIngestItem
) -> InboxIngestResult:
    """Machine-to-machine push (bearer secret, constant-time compare).

    Idempotent on (source, guid): replaying an item returns ``exists``
    with 200 instead of duplicating. Unknown source and wrong secret are
    indistinguishable (404) so the endpoint does not leak existence.
    F107：每次投递落一条事件（delivered/duplicate/failed），失败可重放。"""
    store: InboxStore = _get_inbox_store(request)
    auth = request.headers.get("authorization", "")
    supplied = auth[7:] if auth.lower().startswith("bearer ") else ""
    source = await store.get_source(source_uuid)
    if source is None or not store.secrets_match(supplied, source["secret"]):
        raise InboxSourceNotFound(source_uuid)

    from lumirss.inbox_events import InboxEventStore

    events = InboxEventStore(request.app.state.db)
    raw_payload = item.model_dump()
    try:
        prepared = prepare_ingest_item(item)
        status, ref = await store.ingest(
            source,
            guid=prepared["guid"],
            title=prepared["title"],
            url=prepared["url"],
            author=prepared["author"],
            content_html=prepared["content_html"],
            content_text=prepared["content_text"],
            published_at=prepared["published_at"],
            categories=prepared["categories"],
        )
    except Exception as exc:
        # Connector health stays honest (Q-P2-03): a rejected or failed
        # push surfaces as lastError in the source registry instead of a
        # permanently green connector. Recording is best-effort — never
        # mask the original failure. F107：失败同时落 failed 事件（可重放）。
        message = str(exc) if isinstance(exc, InvalidInboxPayload) else "ingest failed"
        with contextlib.suppress(Exception):
            await store.record_error(source_uuid, message)
        with contextlib.suppress(Exception):
            await events.record(
                source_uuid=source_uuid,
                guid=item.guid,
                status="failed",
                error_summary=message,
                payload=raw_payload,
            )
        raise
    if status == "created":
        # F022：仅「新建」条目应用第一条命中规则（重复投递同 GUID 走
        # exists 路径，不重复触发副作用）。归类失败不影响投递本身。
        with contextlib.suppress(Exception):
            await _apply_inbox_rule(
                request, ref=ref, title=prepared["title"], source=source["name"]
            )
    with contextlib.suppress(Exception):
        await events.record(
            source_uuid=source_uuid,
            guid=prepared["guid"],
            status="delivered" if status == "created" else "duplicate",
            payload=raw_payload,
        )
    return InboxIngestResult(status=status, ref=ref)


# -- F108 载荷契约试跑 ---------------------------------------------------------


@router.post("/api/v1/inbox/sources/{source_uuid}/ingest/dry-run")
async def dry_run_inbox_ingest(
    source_uuid: str, request: Request
) -> dict[str, Any]:
    """F108：与正式 ingest 同一校验函数（prepare_ingest_item）的零写入
    契约试跑：{valid, errors, wouldCreate, notes}。未知字段不 422——
    逐条列进 notes（策略 = 忽略 + 告知）；嵌套超限同样入 notes。"""
    import json as _json

    from pydantic import ValidationError

    store: InboxStore = _get_inbox_store(request)
    source = await store.get_source(source_uuid)
    if source is None:
        raise InboxSourceNotFound(source_uuid)
    errors: list[dict[str, str]] = []
    notes: list[str] = []
    try:
        raw = _json.loads(await request.body() or b"{}")
    except ValueError:
        return {
            "valid": False,
            "errors": [{"field": "body", "reason": "不是合法 JSON"}],
            "wouldCreate": None,
            "notes": [],
        }
    if not isinstance(raw, dict):
        return {
            "valid": False,
            "errors": [{"field": "body", "reason": "载荷必须是 JSON 对象"}],
            "wouldCreate": None,
            "notes": [],
        }
    known_fields = set(InboxIngestItem.model_fields)
    unknown = [key for key in raw if key not in known_fields]
    if unknown:
        notes.append("未知字段（将被忽略）：" + ", ".join(sorted(map(str, unknown))))
    if _raw_depth(raw) > _MAX_NESTING_DEPTH:
        notes.append(f"嵌套深度超过 {_MAX_NESTING_DEPTH} 层（将被忽略深层的值）。")
    try:
        item = InboxIngestItem.model_validate(raw)
    except ValidationError as exc:
        for err in exc.errors():
            field = ".".join(str(part) for part in err.get("loc", ()) or ("body",))
            errors.append({"field": field, "reason": str(err.get("msg", "invalid"))})
        return {
            "valid": False,
            "errors": errors,
            "wouldCreate": None,
            "notes": notes,
        }
    try:
        prepared = prepare_ingest_item(item)
    except InvalidInboxPayload as exc:
        errors.append({"field": "payload", "reason": str(exc)})
        return {
            "valid": False,
            "errors": errors,
            "wouldCreate": None,
            "notes": notes,
        }
    # 重复 GUID 检出（诚实提示：重复投递会被既有幂等吸收，不产生新条目）
    row = await request.app.state.db.fetch_one(
        "SELECT item_uuid FROM library_inbox WHERE source_uuid = ? AND guid = ?",
        (source_uuid, prepared["guid"]),
    )
    would_duplicate = row is not None
    if would_duplicate:
        notes.append("该 guid 已存在：重复投递会被幂等吸收（不产生新条目）。")
    return {
        "valid": True,
        "errors": [],
        "wouldCreate": {"title": prepared["title"], "kind": "api_item"},
        "notes": notes,
        "wouldDuplicate": would_duplicate,
    }


# -- F107 投递事件与失败重放 ----------------------------------------------------


def _event_store(request: Request):
    from lumirss.inbox_events import InboxEventStore

    return InboxEventStore(request.app.state.db)


@router.get("/api/v1/inbox/sources/{source_uuid}/events")
async def list_inbox_events(
    source_uuid: str, request: Request, limit: int = 50
) -> dict[str, Any]:
    store: InboxStore = _get_inbox_store(request)
    if await store.get_source(source_uuid) is None:
        raise InboxSourceNotFound(source_uuid)
    events = await _event_store(request).list_events(source_uuid, limit=limit)
    return {"items": events}


@router.post("/api/v1/inbox/events/{event_id}/replay")
async def replay_inbox_event(event_id: int, request: Request) -> Response:
    """F107：失败事件重放（复用原载荷 + 既有 (source, guid) 幂等）。

    delivered/duplicate → 409 not_replayable；来源已删除 → 404；
    载荷缺失（历史事件/被裁剪）→ 409 payload_missing（诚实）。"""
    store: InboxStore = _get_inbox_store(request)
    event = await _event_store(request).get_event(event_id)
    if event is None:
        raise InboxSourceNotFound(f"event:{event_id}")
    if event["status"] != "failed":
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "not_replayable",
                    "message": f"该事件状态为 {event['status']}，只有 failed 可重放。",
                }
            },
        )
    if not event.get("payload"):
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "payload_missing",
                    "message": "该事件没有可重放的原始载荷。",
                }
            },
        )
    source = await store.get_source(str(event["sourceUuid"]))
    if source is None:
        raise InboxSourceNotFound(str(event["sourceUuid"]))
    try:
        item = InboxIngestItem.model_validate(event["payload"])
        prepared = prepare_ingest_item(item)
    except InvalidInboxPayload as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": {"type": "invalid_payload", "message": str(exc)},
            },
        )
    status, ref = await store.ingest(
        source,
        guid=prepared["guid"],
        title=prepared["title"],
        url=prepared["url"],
        author=prepared["author"],
        content_html=prepared["content_html"],
        content_text=prepared["content_text"],
        published_at=prepared["published_at"],
        categories=prepared["categories"],
    )
    with contextlib.suppress(Exception):
        await _event_store(request).record(
            source_uuid=str(event["sourceUuid"]),
            guid=prepared["guid"],
            status="delivered" if status == "created" else "duplicate",
            payload=event["payload"],
        )
    return JSONResponse(
        status_code=200,
        content={"status": status, "ref": ref, "replayedFrom": event_id},
    )


async def _apply_inbox_rule(
    request: Request, *, ref: str, title: str, source: str
) -> bool:
    """首条命中的启用规则 → 条目归入目标工作区（幂等 add）。

    规则按自身 field 取样本：title 规则比对标题，source 规则比对来源
    名；顺序 = priority（list_rules 已排序），第一条命中生效。"""
    from lumirss.inbox_rules import rule_matches
    from lumirss.workspaces import WorkspaceStore

    rules = await _rule_store(request).list_rules()
    matched = None
    for rule in rules:
        sample = title if rule["field"] == "title" else source
        if rule_matches(rule, field=rule["field"], value=sample, source=source):
            matched = rule
            break
    if matched is None:
        return False
    store = WorkspaceStore(request.app.state.db)
    await store.add_item(matched["targetWorkspaceId"], ref)
    return True


@router.get("/api/v1/inbox/items", response_model=InboxItemList)
async def list_inbox_items(
    request: Request,
    cursor: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    sourceUuid: str | None = None,
) -> InboxItemList:
    """Newest-first page of bare ItemRef rows; the web client renders them
    through POST /api/v1/resolve so display stays registry-owned."""
    if limit < 1 or limit > 50:
        raise InvalidInboxPayload("limit must be between 1 and 50.")
    store = _get_inbox_store(request)
    keyset = _decode_cursor(cursor) if cursor is not None else None
    rows, has_more = await store.list_items(
        source_uuid=sourceUuid, keyset=keyset, limit=limit
    )
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode_cursor(last["createdAt"], _uuid_of(last["ref"]))
    return InboxItemList(
        items=[
            InboxItemRow(
                ref=row["ref"],
                createdAt=row["createdAt"],
                sourceUuid=row["sourceUuid"],
            )
            for row in rows
        ],
        nextCursor=next_cursor,
        hasMore=has_more,
    )


@router.delete("/api/v1/inbox/items/{item_uuid}")
async def delete_inbox_item(request: Request, item_uuid: str) -> dict:
    store = _get_inbox_store(request)
    ref = await store.delete_item(item_uuid)
    if ref is None:
        raise InboxItemNotFound(item_uuid)
    await _rag_mark_stale(request, [ref])
    return {"deleted": True}


def _uuid_of(ref: str) -> str:
    return ref.removeprefix("library:")


# -- F022 收件箱归类规则 ------------------------------------------------------


def _rule_store(request: Request) -> InboxRuleStore:
    from lumirss.deps import _cached_on_app_state

    return _cached_on_app_state(
        request,
        "inbox_rule_store",
        lambda: InboxRuleStore(request.app.state.db),
    )


def _rule_model(rule: dict) -> "InboxRule":
    return InboxRule(**rule)


@router.get("/api/v1/inbox/rules", response_model=InboxRuleList)
async def list_inbox_rules(request: Request) -> "InboxRuleList":
    return InboxRuleList(items=[_rule_model(rule) for rule in await _rule_store(request).list_rules()])


@router.post("/api/v1/inbox/rules", response_model=InboxRule, status_code=201)
async def create_inbox_rule(payload: InboxRuleCreate, request: Request) -> InboxRule:
    rule = await _rule_store(request).create_rule(
        field=payload.field,
        operator=payload.operator,
        value=payload.value,
        target_workspace_id=payload.targetWorkspaceId,
        enabled=payload.enabled,
        priority=payload.priority,
    )
    return _rule_model(rule)


@router.post("/api/v1/inbox/rules/dry-run", response_model=InboxRuleDryRunResult)
async def dry_run_inbox_rule(
    payload: InboxRuleDryRun, request: Request
) -> InboxRuleDryRunResult:
    """样本试跑：纯读、不落库；返回第一条命中规则与解释。"""
    rules = await _rule_store(request).list_rules()
    # F084：目标工作区已归档的规则被跳过（不应用），并在解释中说明。
    archived_ids = {
        str(w.id)
        for w in await _get_workspace_store(request).list_workspaces(
            include_archived=True
        )
        if w.archived
    }
    matched_any = first_matching_rule(
        rules,
        field=payload.field,
        value=payload.value,
        source=payload.source,
    )
    active_rules = [r for r in rules if str(r["targetWorkspaceId"]) not in archived_ids]
    matched = first_matching_rule(
        active_rules,
        field=payload.field,
        value=payload.value,
        source=payload.source,
    )
    if matched is None:
        if matched_any is not None and str(
            matched_any["targetWorkspaceId"]
        ) in archived_ids:
            return InboxRuleDryRunResult(
                matchedRule=None,
                explanation=(
                    f"命中规则的目标工作区「{matched_any['targetWorkspaceId']}」"
                    "已归档，该规则跳过（目标已归档）。"
                ),
            )
        return InboxRuleDryRunResult(
            matchedRule=None,
            explanation="没有命中的启用规则；条目将保持未归类。",
        )
    operator_text = "包含" if matched["operator"] == "contains" else "等于"
    scope = matched["field"] == "title" and "标题" or "来源"
    return InboxRuleDryRunResult(
        matchedRule=_rule_model(matched),
        explanation=(
            f"第 {matched['priority'] + 1} 条规则命中：{scope}"
            f"「{payload.value}」{operator_text}「{matched['value']}」"
            f"→ 归入工作区 {matched['targetWorkspaceId']}。"
        ),
    )


@router.patch("/api/v1/inbox/rules/{rule_id}", response_model=InboxRule)
async def patch_inbox_rule(
    rule_id: int, payload: InboxRuleUpdate, request: Request
) -> InboxRule:
    rule = await _rule_store(request).update_rule(
        rule_id, payload.model_dump(exclude_none=False)
    )
    if rule is None:
        raise InboxRuleNotFound(str(rule_id))
    return _rule_model(rule)


@router.post("/api/v1/inbox/rules/{rule_id}/move", response_model=InboxRule)
async def move_inbox_rule(
    rule_id: int, request: Request, direction: str = "up"
) -> InboxRule:
    """priority 上下移（应用顺序 = 列表顺序）。"""
    if direction not in ("up", "down"):
        raise InvalidInboxPayload("direction must be 'up' or 'down'.")
    rule = await _rule_store(request).move_rule(rule_id, direction)
    if rule is None:
        raise InboxRuleNotFound(str(rule_id))
    return _rule_model(rule)


@router.delete("/api/v1/inbox/rules/{rule_id}", status_code=204)
async def delete_inbox_rule(rule_id: int, request: Request) -> Response:
    deleted = await _rule_store(request).delete_rule(rule_id)
    if not deleted:
        raise InboxRuleNotFound(str(rule_id))
    return Response(status_code=204)
