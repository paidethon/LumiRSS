"""Tags + graph routes (phase2 G8)."""

from fastapi import APIRouter, Request, Response

from lumirss.graph import build_graph
from lumirss.models import (
    GraphResponse,
    TagAssignRequest,
    TagBinding,
    TagListResponse,
    TagRenameRequest,
    TagSuggestionsResponse,
)
from lumirss.tags import (
    TagInvalid,
    TagNotFound,
    TagStore,
)

from ..deps import _get_tag_store

router = APIRouter()


@router.get("/api/v1/tags", response_model=TagListResponse)
async def list_tags(request: Request, q: str | None = None) -> TagListResponse:
    store: TagStore = _get_tag_store(request)
    return TagListResponse(
        items=[tag.to_dict() for tag in await store.list_tags(q=q)]
    )


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


@router.post("/api/v1/tags/assign", response_model=TagBinding, status_code=201)
async def assign_tag(payload: TagAssignRequest, request: Request) -> TagBinding:
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


@router.get("/api/v1/tags/item/{item_ref}")
async def item_tags(request: Request, item_ref: str) -> dict:
    store: TagStore = _get_tag_store(request)
    return {"items": await store.tags_for_item(item_ref, include_suggested=True)}


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
    title_hint = item_ref
    example = '["标签A","标签B","标签C"]'
    prompt = (
        "为下面的条目建议 3 个简短中文标签（每个不超过 12 个字），"
        f"只输出 JSON 数组，例如 {example}。"
        f"条目标识：{title_hint[:200]}"
    )
    try:
        message = await provider.chat_completion(
            messages=[{"role": "user", "content": prompt}]
        )
        import json

        raw = str(message.get("content") or "[]")
        start, end = raw.find("["), raw.rfind("]")
        names = json.loads(raw[start : end + 1]) if start >= 0 and end > start else []
        names = [str(n)[:20] for n in names if isinstance(n, str)][:3]
    except Exception as exc:  # noqa: BLE001 — honest failure
        raise TagInvalid(f"标签建议生成失败：{exc}") from exc
    _ = existing
    return TagSuggestionsResponse(suggestions=names)


@router.post("/api/v1/tags/suggestions/{item_ref}/attach", response_model=TagBinding, status_code=201)
async def attach_suggestion(
    item_ref: str, payload: TagAssignRequest, request: Request
) -> TagBinding:
    """Persist an accepted suggestion as suggested; caller then accepts."""
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
