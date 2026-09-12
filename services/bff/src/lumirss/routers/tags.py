"""Tags + graph routes (phase2 G8)."""

import json

from fastapi import APIRouter, Request, Response

from lumirss.graph import build_graph
from lumirss.models import (
    GraphResponse,
    ResolvedItem,
    TagAssignRequest,
    TagBinding,
    TagItemsResponse,
    TagListResponse,
    TagRenameRequest,
    TagSuggestionsResponse,
)
from lumirss.sources import ItemRefUnresolvable, ensure_resolvable, resolve_item
from lumirss.tags import (
    TagInvalid,
    TagNotFound,
    TagStore,
)

from ..deps import (
    _get_source_registry,
    _get_tag_store,
)

router = APIRouter()


async def _require_resolvable(request: Request, item_ref: str) -> None:
    """Attach-style writes validate the ref resolves (ADR 0004)."""
    try:
        await ensure_resolvable(_get_source_registry(request), item_ref)
    except ItemRefUnresolvable as exc:
        raise TagInvalid("引用的内容不存在，无法打标签。") from exc


@router.get("/api/v1/tags", response_model=TagListResponse)
async def list_tags(request: Request, q: str | None = None) -> TagListResponse:
    store: TagStore = _get_tag_store(request)
    return TagListResponse(
        items=[tag.to_dict() for tag in await store.list_tags(q=q)]
    )


# Static paths MUST be declared before the /{tag_id} routes: FastAPI
# matches in declaration order, and "assign" would otherwise be captured
# by /{tag_id} and fail int parsing (this bug silently disabled detach
# for as long as no client called it — P0-10a).
@router.post("/api/v1/tags/assign", response_model=TagBinding, status_code=201)
async def assign_tag(payload: TagAssignRequest, request: Request) -> TagBinding:
    await _require_resolvable(request, payload.itemRef)
    store: TagStore = _get_tag_store(request)
    binding = await store.attach(
        payload.itemRef, payload.name, origin=payload.origin
    )
    return TagBinding(**binding)


@router.delete("/api/v1/tags/assign", status_code=204)
async def detach_tag(payload: TagAssignRequest, request: Request) -> Response:
    store: TagStore = _get_tag_store(request)
    removed = await store.detach(payload.itemRef, payload.name, origin=payload.origin)
    if not removed:
        raise TagNotFound(payload.name)
    return Response(status_code=204)


@router.patch("/api/v1/tags/{tag_id}", response_model=TagBinding)
async def rename_tag(tag_id: int, payload: TagRenameRequest, request: Request) -> TagBinding:
    store: TagStore = _get_tag_store(request)
    record = await store.rename(tag_id, payload.name)
    return TagBinding(**record.to_dict())


@router.delete("/api/v1/tags/{tag_id}", status_code=204)
async def delete_tag(tag_id: int, request: Request) -> Response:
    store: TagStore = _get_tag_store(request)
    deleted = await store.delete(tag_id)
    if not deleted:
        raise TagNotFound(str(tag_id))
    return Response(status_code=204)


@router.get("/api/v1/tags/item/{item_ref}")
async def item_tags(request: Request, item_ref: str) -> dict:
    store: TagStore = _get_tag_store(request)
    return {"items": await store.tags_for_item(item_ref, include_suggested=True)}


@router.get("/api/v1/tags/{tag_id}/items", response_model=TagItemsResponse)
async def tag_items(
    tag_id: int, request: Request, limit: int = 100
) -> TagItemsResponse:
    """Server-driven list of one tag's items, each resolved (P0-10i):
    the client never filters a partially loaded timeline to show a tag."""
    limit = max(1, min(limit, 200))
    store: TagStore = _get_tag_store(request)
    refs = await store.item_refs_for_tag(tag_id, limit=limit)
    registry = _get_source_registry(request)
    import asyncio

    resolved = list(await asyncio.gather(*(resolve_item(registry, ref) for ref in refs)))
    return TagItemsResponse(
        items=[
            ResolvedItem(
                ref=view.ref,
                domain=view.domain,
                kind=view.kind,
                title=view.title,
                source=view.source,
                datetime=view.datetime,
                excerpt=view.excerpt,
                url=view.url,
                stale=view.stale,
                payload=view.payload,
            )
            for view in resolved
        ]
    )


@router.get("/api/v1/tags/suggestions/{item_ref}", response_model=TagSuggestionsResponse)
async def tag_suggestions(item_ref: str, request: Request) -> TagSuggestionsResponse:
    """AI suggestions are computed, NEVER stored here (assign-with-ai or
    accept endpoints persist only after explicit user action)."""
    from lumirss.deps import _provider_or_none

    provider = await _provider_or_none(request)
    if provider is None:
        raise TagInvalid("AI 未配置，无法生成标签建议。")
    store: TagStore = _get_tag_store(request)
    existing = [t["name"] for t in await store.tags_for_item(item_ref)]
    # Prompt with the content's real title/excerpt, not the opaque ref.
    resolved = await resolve_item(_get_source_registry(request), item_ref)
    title_hint = resolved.title if not resolved.stale else item_ref
    excerpt_hint = f"\n摘要：{resolved.excerpt[:160]}" if resolved.excerpt else ""
    avoid = (
        f"已有标签（不要重复建议）：{'、'.join(existing)}。" if existing else ""
    )
    example = '["标签A","标签B","标签C"]'
    prompt = (
        "为下面的条目建议 3 个简短中文标签（每个不超过 12 个字），"
        f"只输出 JSON 数组，例如 {example}。{avoid}"
        f"条目标题：{title_hint[:200]}{excerpt_hint}"
    )
    try:
        message = await provider.chat_completion(
            messages=[{"role": "user", "content": prompt}]
        )
        raw = str(message.get("content") or "[]")
        start, end = raw.find("["), raw.rfind("]")
        names = json.loads(raw[start : end + 1]) if start >= 0 and end > start else []
        names = [str(n)[:20] for n in names if isinstance(n, str)][:3]
    except Exception as exc:  # noqa: BLE001 — honest failure
        raise TagInvalid(f"标签建议生成失败：{exc}") from exc
    return TagSuggestionsResponse(suggestions=names)


@router.post("/api/v1/tags/suggestions/{item_ref}/attach", response_model=TagBinding, status_code=201)
async def attach_suggestion(
    item_ref: str, payload: TagAssignRequest, request: Request
) -> TagBinding:
    """Persist an accepted suggestion as suggested; caller then accepts."""
    await _require_resolvable(request, item_ref)
    store: TagStore = _get_tag_store(request)
    binding = await store.attach(
        item_ref, payload.name, origin="ai", status="suggested"
    )
    return TagBinding(**binding)


@router.post("/api/v1/tags/suggestions/{item_ref}/accept", response_model=TagBinding)
async def accept_suggestion(
    item_ref: str, payload: TagAssignRequest, request: Request
) -> TagBinding:
    store: TagStore = _get_tag_store(request)
    result = await store.accept_suggestion(item_ref, payload.name)
    return TagBinding(**result)


@router.get("/api/v1/graph", response_model=GraphResponse)
async def relationship_graph(
    request: Request, scope: str = "all", max: int = 2000
) -> GraphResponse:
    """Pure derived, read-only graph; truncation reported honestly."""
    db = request.app.state.db
    result = await build_graph(db, scope=scope, max_nodes=max(10, min(max, 2000)))
    return GraphResponse(**result)
