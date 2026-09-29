"""NEW-312 网页选区剪藏包路由 — 选区包创建 / 按页列出 / 删除。

- POST   /api/v1/library/clip-selections        {url, pageTitle, selections[], clipRef?} → 201
- GET    /api/v1/library/clip-selections        ?url=… → 选区包列表（按页过滤）
- GET    /api/v1/library/clip-selections/{id}   → 单包
- DELETE /api/v1/library/clip-selections/{id}   → 204

零抓取：路由层不做任何网络请求；URL 只做结构校验。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.library_clips import ClipNotFound
from lumirss.new312_clip_selections import ClipSelectionStore, SelectionInvalid

router = APIRouter()


class SelectionItem(BaseModel):
    model_config = {"extra": "forbid"}

    text: str = Field(min_length=1, max_length=2000)
    note: str = Field(default="", max_length=500)


class SelectionPackageCreate(BaseModel):
    model_config = {"extra": "forbid"}

    url: str = Field(min_length=1, max_length=2048)
    pageTitle: str = Field(default="", max_length=500)
    selections: list[SelectionItem] = Field(min_length=1, max_length=20)
    clipRef: str | None = None


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> ClipSelectionStore:
    return ClipSelectionStore(request.app.state.db)


@router.post("/api/v1/library/clip-selections", status_code=201)
async def create_selection_package(
    payload: SelectionPackageCreate, request: Request
) -> Response:
    try:
        result = await _store(request).create_package(
            url=payload.url,
            page_title=payload.pageTitle,
            selections=[
                {"text": item.text, "note": item.note} for item in payload.selections
            ],
            clip_ref=payload.clipRef,
        )
    except SelectionInvalid as exc:
        return _error(422, "invalid_selection_package", str(exc))
    except ClipNotFound:
        return _error(404, "clip_not_found", "要挂接的剪藏不存在。")
    return JSONResponse(result, status_code=201)


@router.get("/api/v1/library/clip-selections")
async def list_selection_packages(request: Request, url: str | None = None) -> Response:
    try:
        packages = await _store(request).list_packages(url=url)
    except SelectionInvalid as exc:
        return _error(422, "invalid_selection_package", str(exc))
    return JSONResponse({"packages": packages})


@router.get("/api/v1/library/clip-selections/{package_id}")
async def get_selection_package(package_id: str, request: Request) -> Response:
    package = await _store(request).get_package(package_id)
    if package is None:
        return _error(404, "selection_package_not_found", "选区剪藏包不存在。")
    return JSONResponse(package)


@router.delete("/api/v1/library/clip-selections/{package_id}", status_code=204)
async def delete_selection_package(package_id: str, request: Request) -> Response:
    deleted = await _store(request).delete_package(package_id)
    if not deleted:
        return _error(404, "selection_package_not_found", "选区剪藏包不存在。")
    return Response(status_code=204)
