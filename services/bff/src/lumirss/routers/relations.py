"""F021 手工关联内容 routes。

- POST /api/v1/relations：创建（自关联/坏 ref → 422；同向同备注幂等；
  同向不同备注 → 409）；
- GET /api/v1/relations?item_ref=：双向列表，另一端按 registry 解析，
  失效目标诚实标记 stale:true（关系保留，不自动删除）；
- DELETE /api/v1/relations/{id}：解除（204 / 404）。

创建是 attach 式写入：两端引用必须可解析（与 tags assign 同一 ADR 0004
语义）；之后目标被删除只降级为 stale，不回收关系。
"""

from fastapi import APIRouter, Request, Response

from lumirss.item_relations import (
    ItemRelationStore,
    RelationDuplicate,
    RelationInvalid,
    RelationNotFound,
)
from lumirss.models import (
    RelationCreate,
    RelationList,
    RelationView,
)
from lumirss.sources import ItemRefUnresolvable, ensure_resolvable

from ..deps import _get_source_registry

router = APIRouter()

_MAX_RELATIONS_PER_REQUEST_LIST = 500


def _store(request: Request) -> ItemRelationStore:
    from lumirss.deps import _cached_on_app_state

    return _cached_on_app_state(
        request,
        "item_relation_store",
        lambda: ItemRelationStore(request.app.state.db),
    )


async def _resolve_end(request: Request, relation: dict) -> dict:
    """Attach resolved views for BOTH ends; a deleted target degrades to
    stale:true — never an error, never an auto-delete."""
    from lumirss.sources import resolve_item

    registry = _get_source_registry(request)
    src = await resolve_item(registry, relation["srcRef"])
    dst = await resolve_item(registry, relation["dstRef"])
    view = dict(relation)
    view["src"] = src.to_dict()
    view["dst"] = dst.to_dict()
    # stale = 任一端失效（图谱跳转前按此校验）。
    view["stale"] = bool(src.stale or dst.stale)
    return view


@router.post("/api/v1/relations", response_model=RelationView, status_code=201)
async def create_relation(payload: RelationCreate, request: Request) -> dict:
    registry = _get_source_registry(request)
    for ref in (payload.srcRef, payload.dstRef):
        try:
            await ensure_resolvable(registry, ref)
        except ItemRefUnresolvable as exc:
            raise RelationInvalid("引用的内容不存在，无法建立关联。") from exc
    relation = await _store(request).create(
        payload.srcRef, payload.dstRef, payload.note
    )
    return await _resolve_end(request, relation)


@router.get("/api/v1/relations", response_model=RelationList)
async def list_relations(request: Request, itemRef: str) -> RelationList:
    relations = await _store(request).list_for_item(itemRef)
    views = [await _resolve_end(request, relation) for relation in relations]
    return RelationList(items=views[:_MAX_RELATIONS_PER_REQUEST_LIST])


@router.delete("/api/v1/relations/{relation_id}", status_code=204)
async def delete_relation(relation_id: int, request: Request) -> Response:
    deleted = await _store(request).delete(relation_id)
    if not deleted:
        raise RelationNotFound(str(relation_id))
    return Response(status_code=204)


_ = (RelationDuplicate,)  # mapped in errors.py
