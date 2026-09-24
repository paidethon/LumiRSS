"""F051/F052 批注路由 — CRUD、跨篇检索、Markdown 汇编导出。

导出（F052）按文章分组，每条含 > 摘录、我的批注、来源标题+日期+定位
链接（F015 段落锚点格式，无凭据）；锚点失效（原文已变化）时在条目
上诚实标注。导出内容做 Markdown 转义（摘录/批注中的 ``#``/``>``/
反引号不破坏文档结构）。
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.annotation_store import (
    MAX_EXCERPT,
    MAX_NOTE,
    AnnotationInvalid,
    AnnotationStore,
)
from lumirss.models import (
    AnnotationExportDelta,
    AnnotationExportMarkResult,
)

router = APIRouter()


class AnnotationCreate(BaseModel):
    """POST /api/v1/annotations body。"""

    model_config = {"extra": "forbid"}

    entryRef: str
    anchor: dict[str, object]
    excerpt: str | None = Field(default=None, max_length=MAX_EXCERPT)
    note: str | None = Field(default=None, max_length=MAX_NOTE)
    color: str = "yellow"


class AnnotationUpdate(BaseModel):
    """PATCH /api/v1/annotations/{id} body。"""

    model_config = {"extra": "forbid"}

    note: str | None = Field(default=None, max_length=MAX_NOTE)
    excerpt: str | None = Field(default=None, max_length=MAX_EXCERPT)
    color: str | None = None


class AnnotationExportRequest(BaseModel):
    """POST /api/v1/annotations/export body（范围：全部 / 当前筛选）。"""

    model_config = {"extra": "forbid"}

    entryRefs: list[str] | None = None
    q: str | None = None


class AnnotationExportMarkRequest(BaseModel):
    """POST /api/v1/annotations/export-mark body（N137 导出水位回标）。"""

    model_config = {"extra": "forbid"}

    ids: list[str] = Field(min_length=1)


def _invalid_response(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "invalid_annotation", "message": message}},
    )


@router.get("/api/v1/annotations")
async def list_annotations(
    request: Request,
    entryRef: str | None = None,
    q: str | None = None,
    cursor: str | None = None,
) -> Response:
    store = AnnotationStore(request.app.state.db)
    if entryRef is not None:
        items = await store.list_for_entry(entryRef)
        return JSONResponse({"items": items, "nextCursor": None})
    after = None
    if cursor:
        parts = cursor.split("|", 1)
        if len(parts) != 2:
            return _invalid_response("cursor 无效。")
        after = (parts[0], parts[1])
    items, next_cursor = await store.search(q, after)
    return JSONResponse({"items": items, "nextCursor": next_cursor})


@router.post("/api/v1/annotations", status_code=201)
async def create_annotation(payload: AnnotationCreate, request: Request) -> Response:
    store = AnnotationStore(request.app.state.db)
    try:
        item = await store.create(
            entry_ref=payload.entryRef,
            anchor=payload.anchor,
            excerpt=payload.excerpt,
            note=payload.note,
            color=payload.color,
        )
    except AnnotationInvalid as exc:
        return _invalid_response(str(exc))
    return JSONResponse(status_code=201, content=item)


@router.patch("/api/v1/annotations/{annotation_id}")
async def update_annotation(
    annotation_id: str, payload: AnnotationUpdate, request: Request
) -> Response:
    store = AnnotationStore(request.app.state.db)
    try:
        item = await store.update(
            annotation_id, note=payload.note, color=payload.color, excerpt=payload.excerpt
        )
    except AnnotationInvalid as exc:
        return _invalid_response(str(exc))
    if item is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "annotation_not_found", "message": "批注不存在。"}},
        )
    return JSONResponse(item)


@router.delete("/api/v1/annotations/{annotation_id}", status_code=204)
async def delete_annotation(annotation_id: str, request: Request) -> Response:
    store = AnnotationStore(request.app.state.db)
    deleted = await store.delete(annotation_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "annotation_not_found", "message": "批注不存在。"}},
        )
    return Response(status_code=204)


def _md_escape(text: str) -> str:
    """Markdown 结构转义：行首 #/>/- 与行内反引号不破坏文档结构。"""
    cleaned = text.replace("`", "\\`").replace("\r", "")
    lines = []
    for line in cleaned.split("\n"):
        if line.startswith(("#", ">", "-", "1.")):
            line = "\\" + line
        lines.append(line)
    return "\n".join(lines)


@router.post("/api/v1/annotations/export-mark", response_model=AnnotationExportMarkResult)
async def mark_annotations_exported(
    payload: AnnotationExportMarkRequest, request: Request
) -> Response:
    """N137：成功导出后回标水位（幂等：重复调用只追加日志行，水位只
    前进，增量查询不会重复计数）。ids 为空 → 422。"""
    store = AnnotationStore(request.app.state.db)
    result = await store.mark_exported(payload.ids)
    return JSONResponse(AnnotationExportMarkResult(**result).model_dump())


@router.get(
    "/api/v1/annotations/export-delta", response_model=AnnotationExportDelta
)
async def annotations_export_delta(
    request: Request,
    entryRef: str | None = None,
) -> Response:
    """N137：增量导出预览 —— 水位之后的新增/修改批注计数（可按文章
    收窄）。从未导出 → lastExportedAt=null 且全部计为新增（诚实）。"""
    store = AnnotationStore(request.app.state.db)
    delta = await store.export_delta(entry_ref=entryRef)
    return JSONResponse(AnnotationExportDelta(**delta).model_dump())


@router.post("/api/v1/annotations/export")
async def export_annotations(payload: AnnotationExportRequest, request: Request) -> Response:
    """F052：批注汇编导出（Markdown 下载）。空选择 → 422。"""
    store = AnnotationStore(request.app.state.db)
    if payload.entryRefs is not None and len(payload.entryRefs) == 0:
        return _invalid_response("导出范围为空。")
    if payload.entryRefs is not None:
        items: list[dict[str, object]] = []
        for ref in payload.entryRefs:
            items.extend(await store.list_for_entry(ref))
    else:
        items, _ = await store.search(payload.q, None)
    if not items:
        return _invalid_response("没有可导出的批注。")

    by_entry: dict[str, list[dict[str, object]]] = {}
    for item in items:
        by_entry.setdefault(str(item["entryRef"]), []).append(item)
    lines: list[str] = ["# 批注汇编", ""]
    from lumirss.util import utc_now

    lines.append(f"导出于 {utc_now()} · 共 {len(items)} 条批注 · {len(by_entry)} 篇文章")
    for entry_ref, entry_items in by_entry.items():
        first = entry_items[0]
        anchor = first.get("anchor") or {}
        para = str(anchor.get("paraId", "")) if isinstance(anchor, dict) else ""
        deep_link = f"/reader?entry={entry_ref}" + (f"&para={para}" if para else "")
        lines += ["", f"## 文章 {entry_ref}", "", f"[打开原文（定位段落）]({deep_link})"]
        for item in entry_items:
            lines += ["", "> " + _md_escape(str(item["excerpt"]) or "（无摘录）")]
            note = str(item["note"] or "")
            lines += ["", f"我的批注：{_md_escape(note) if note else '（无批注）'}"]
            stale_anchor = bool((item.get("anchor") or {}).get("stale")) if isinstance(item.get("anchor"), dict) else False
            if stale_anchor:
                lines += ["", "（原文已变化：锚点可能不再准确定位）"]
    body = "\n".join(lines) + "\n"
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="lumi-annotations.md"'},
    )
