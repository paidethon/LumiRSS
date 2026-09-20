"""F076 图谱命名视图路由 — CRUD（同名覆盖确认流）。"""

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.graph_views_store import (
    GraphViewExists,
    GraphViewStore,
)

router = APIRouter()


class GraphViewBody(BaseModel):
    """POST /api/v1/graph/views body（F076）。"""

    name: str = Field(min_length=1, max_length=50)
    layout: dict[str, dict[str, float]] | None = None
    filters: dict[str, Any] | None = None
    focusNode: str | None = None
    # 同名已存在时必须显式 overwrite=true 才覆盖（否则 409）。
    overwrite: bool = False


@router.get("/api/v1/graph/views")
async def list_graph_views(request: Request) -> dict[str, Any]:
    store = GraphViewStore(request.app.state.db)
    return {"items": await store.list_views()}


@router.post("/api/v1/graph/views")
async def create_graph_view(payload: GraphViewBody, request: Request) -> Any:
    store = GraphViewStore(request.app.state.db)
    try:
        view = await store.create(
            payload.name,
            payload.layout,
            payload.filters,
            payload.focusNode,
            overwrite=payload.overwrite,
        )
    except GraphViewExists as exc:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "graph_view_exists",
                    "message": f"视图「{exc.name}」已存在；请改名或确认覆盖。",
                }
            },
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_graph_view", "message": str(exc)}},
        )
    return view


@router.delete("/api/v1/graph/views/{view_id}", status_code=204)
async def delete_graph_view(view_id: str, request: Request) -> Response:
    store = GraphViewStore(request.app.state.db)
    deleted = await store.delete(view_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "graph_view_not_found", "message": "视图不存在。"}},
        )
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# F077：关系路径查找（BFS 于派生图：标签/工作区/wikilink/手工关系边）。
# ---------------------------------------------------------------------------


class GraphPathBody(BaseModel):
    """POST /api/v1/graph/path body（F077）。"""

    srcRef: str = Field(min_length=1)
    dstRef: str = Field(min_length=1)
    maxDepth: int = Field(default=4, ge=1, le=4)


@router.post("/api/v1/graph/path", response_model=None)
async def find_graph_path(payload: GraphPathBody, request: Request) -> Any:
    """两节点间路径（F077）：paths ≤5（节点序列+边类型序列）；
    环安全；不可达 → {paths: [], reachable: false}。"""
    from lumirss.graph_paths import find_paths

    if payload.srcRef.strip() == "" or payload.dstRef.strip() == "":
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_path_request", "message": "路径端点不能为空。"}},
        )
    return await find_paths(
        request.app.state.db,
        src_ref=payload.srcRef.strip(),
        dst_ref=payload.dstRef.strip(),
        max_depth=payload.maxDepth,
    )
