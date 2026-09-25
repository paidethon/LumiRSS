"""F051/F052 批注路由 — CRUD、跨篇检索、Markdown 汇编导出。

导出（F052）按文章分组，每条含 > 摘录、我的批注、来源标题+日期+定位
链接（F015 段落锚点格式，无凭据）；锚点失效（原文已变化）时在条目
上诚实标注。导出内容做 Markdown 转义（摘录/批注中的 ``#``/``>``/
反引号不破坏文档结构）。

N071 原文漂移修复：锚点失效后对当前正文块重检存量引文
（repair-candidates），用户从候选中选定后 rebind（anchor + hash 更新，
旧锚点进 annotation_repair_log，cap 10）；最高相似度 < 0.5 → 拒绝
自动修复（只能手动改文本），绝不假装命中。

N073 颜色语义：调色板颜色的语义标签（color-labels PUT/GET）；列表
支持 color= 过滤；未命名的颜色诚实回显原始色名。

N075 引用格式导出：citeBibliography=true 时每篇文章追加
「引用格式：标题 — 来源, 日期」；标题/来源/日期缺失逐项以「不详」
占位 —— 只用条目既有元数据（search_entries 投影），绝不 AI 补全。
"""

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.annotation_repair import (
    REPAIR_MIN_SCORE,
    repair_candidates,
    score_quote,
    split_blocks,
)
from lumirss.annotation_store import (
    COLORS,
    MAX_EXCERPT,
    MAX_NOTE,
    AnchorHashConflict,
    AnnotationInvalid,
    AnnotationStore,
)
from lumirss.models import (
    AnnotationColorLabelList,
    AnnotationColorLabelPut,
    AnnotationExportDelta,
    AnnotationExportMarkResult,
    AnnotationMigrateApplyItem,
    AnnotationMigrateApplyItemResult,
    AnnotationMigrateApplyRequest,
    AnnotationMigrateApplyResponse,
    AnnotationMigratePreviewRequest,
    AnnotationMigratePreviewResponse,
    AnnotationRepairCandidatesResult,
    AnnotationRepairRequest,
    AnnotationRepairResult,
    AnnotationView,
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
    """POST /api/v1/annotations/export body（范围：全部 / 当前筛选 /
    N072 精选篮）。basketId 与 entryRefs/q 互斥（篮是独立导出维度）。"""

    model_config = {"extra": "forbid"}

    entryRefs: list[str] | None = None
    q: str | None = None
    citeBibliography: bool = False
    basketId: str | None = None


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
    color: str | None = None,
    cursor: str | None = None,
) -> Response:
    """跨篇检索/单篇列表；N073：可选 color= 过滤（调色板原始色名）。"""
    store = AnnotationStore(request.app.state.db)
    if color is not None and color not in COLORS:
        return _invalid_response("color 非法。")
    if entryRef is not None:
        items = await store.list_for_entry(entryRef, color=color)
        return JSONResponse({"items": items, "nextCursor": None})
    after = None
    if cursor:
        parts = cursor.split("|", 1)
        if len(parts) != 2:
            return _invalid_response("cursor 无效。")
        after = (parts[0], parts[1])
    items, next_cursor = await store.search(q, after, color=color)
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


# ---- N071 原文漂移修复 -------------------------------------------------------


def _error_response(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


async def _entry_content_text(request: Request, entry_ref: str) -> str | None:
    """当前正文文本（FreshRSS 适配器，per-user 绑定）。不可达 → None
    （调用方诚实返回 entry_unavailable，绝不使用任何缓存正文）。"""
    from lumirss.deps import _get_adapter_or_none
    from lumirss.entryref import InvalidEntryReference, decode_entry_ref

    adapter = _get_adapter_or_none(request)
    if adapter is None:
        return None
    try:
        detail = await adapter.get_entry(decode_entry_ref(entry_ref))
    except (Exception, InvalidEntryReference):  # noqa: BLE001 — 上游/解码失败同口径
        return None
    return detail.contentText or ""


@router.get(
    "/api/v1/annotations/{annotation_id}/repair-candidates",
    response_model=AnnotationRepairCandidatesResult,
)
async def annotation_repair_candidates(
    annotation_id: str, request: Request
) -> Response:
    """重检存量引文在当前正文块中的位置：exact/prefix/fuzzy ≥0.8 →
    候选列表（最多 5 条，分数降序）。引文为空 / 原文不可达 → 422 诚实
    拒绝（不猜）。"""
    store = AnnotationStore(request.app.state.db)
    item = await store.get(annotation_id)
    if item is None:
        return _error_response(404, "annotation_not_found", "批注不存在。")
    anchor = item["anchor"] if isinstance(item["anchor"], dict) else {}
    quote = str(item["excerpt"] or anchor.get("exact") or "")
    if quote.strip() == "":
        return _error_response(422, "repair_no_quote", "该批注没有可检索的引文。")
    content_text = await _entry_content_text(request, str(item["entryRef"]))
    if content_text is None:
        return _error_response(
            422,
            "entry_unavailable",
            "原文暂不可达，无法生成修复候选（不做缓存正文）。",
        )
    blocks = split_blocks(content_text)
    candidates = repair_candidates(quote, blocks, prefix=str(anchor.get("prefix") or ""))
    result = AnnotationRepairCandidatesResult(
        annotationId=item["id"],
        entryRef=item["entryRef"],
        quote=quote,
        candidates=[
            {
                "blockIndex": candidate["blockIndex"],
                "score": candidate["score"],
                "excerpt": candidate["excerpt"],
            }
            for candidate in candidates
        ],
    )
    return JSONResponse(result.model_dump())


@router.post(
    "/api/v1/annotations/{annotation_id}/repair",
    response_model=AnnotationRepairResult,
)
async def repair_annotation(
    annotation_id: str, payload: AnnotationRepairRequest, request: Request
) -> Response:
    """按用户选定的块重新绑定（anchor + anchor_hash 更新；旧锚点进
    annotation_repair_log，cap 10）。当前正文里最高相似度 < 0.5 → 422
    （repair_refused：只支持手动修复，不假装命中）。"""
    store = AnnotationStore(request.app.state.db)
    item = await store.get(annotation_id)
    if item is None:
        return _error_response(404, "annotation_not_found", "批注不存在。")
    content_text = await _entry_content_text(request, str(item["entryRef"]))
    if content_text is None:
        return _error_response(
            422,
            "entry_unavailable",
            "原文暂不可达，无法核对修复位置（不做缓存正文）。",
        )
    blocks = split_blocks(content_text)
    if payload.blockIndex >= len(blocks):
        return _error_response(422, "repair_block_out_of_range", "blockIndex 超出当前正文范围。")
    quote = payload.quoteText.strip()
    if quote == "":
        return _error_response(422, "repair_no_quote", "quoteText 不能为空。")
    best = max(score_quote(quote, block) for block in blocks)
    if best < REPAIR_MIN_SCORE:
        return _error_response(
            422,
            "repair_refused",
            f"未能在当前原文中找到足够接近的位置（最高相似度 {best:.2f}），请手动修复。",
        )
    bound_score = score_quote(quote, blocks[payload.blockIndex])
    if bound_score < REPAIR_MIN_SCORE:
        return _error_response(
            422,
            "repair_refused",
            "所选块与引文差异过大（相似度不足 0.5），请重新选择。",
        )
    try:
        updated = await store.rebind(
            annotation_id,
            block_index=payload.blockIndex,
            quote=quote,
            score=round(bound_score, 4),
        )
    except AnchorHashConflict as exc:
        return _error_response(409, "anchor_conflict", str(exc))
    if updated is None:
        return _error_response(404, "annotation_not_found", "批注不存在。")
    result = AnnotationRepairResult(
        annotation=AnnotationView(**updated),
        blockIndex=payload.blockIndex,
        score=round(bound_score, 4),
    )
    return JSONResponse(result.model_dump())


# ---- N073 批注颜色语义 -------------------------------------------------------


@router.get(
    "/api/v1/annotations/color-labels", response_model=AnnotationColorLabelList
)
async def get_color_labels(request: Request) -> Response:
    """全调色板颜色标签（label 空 = 未命名 → Web 诚实显示原始色名）。"""
    store = AnnotationStore(request.app.state.db)
    items = await store.get_color_labels()
    return JSONResponse(AnnotationColorLabelList(items=items).model_dump())


@router.put("/api/v1/annotations/color-labels", response_model=AnnotationColorLabelList)
async def put_color_label(payload: AnnotationColorLabelPut, request: Request) -> Response:
    """upsert 单个颜色标签；返回全调色板最新标签。"""
    store = AnnotationStore(request.app.state.db)
    try:
        await store.set_color_label(payload.color, payload.label.strip())
    except AnnotationInvalid as exc:
        return _invalid_response(str(exc))
    items = await store.get_color_labels()
    return JSONResponse(AnnotationColorLabelList(items=items).model_dump())


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


def _bibliography_line(meta: dict[str, str | None]) -> str:
    """N075 引用格式行：`标题 — 来源, 日期`。标题/来源/日期缺失逐项
    以「不详」占位（诚实显式 token）——只用条目既有元数据，绝不 AI 补全。"""
    unknown = "不详"
    title = (meta.get("title") or "").strip() or unknown
    source = (meta.get("source") or "").strip() or unknown
    date = (meta.get("date") or "").strip() or unknown
    return f"引用格式：{title} — {source}, {date}"


async def _entry_bibliography_meta(db: Any, entry_ref: str) -> dict[str, str | None]:
    """条目元数据（标题/来源/日期）——search_entries 投影（本就随同步
    维护的可重建投影，含标题与来源名；不触上游，导出离线可用）。"""
    row = await db.fetch_one(
        "SELECT title, feed_title, published_at FROM search_entries WHERE entry_ref = ?",
        (entry_ref,),
    )
    if row is None:
        return {"title": None, "source": None, "date": None}
    published = str(row["published_at"] or "").strip()
    date = published[:10] if len(published) >= 10 and published[4] == "-" and published[7] == "-" else None
    return {
        "title": str(row["title"] or ""),
        "source": str(row["feed_title"] or ""),
        "date": date,
    }


@router.post("/api/v1/annotations/export")
async def export_annotations(payload: AnnotationExportRequest, request: Request) -> Response:
    """F052：批注汇编导出（Markdown 下载）。空选择 → 422。N075：
    citeBibliography=true 时每篇文章追加引用格式行（缺失项「不详」）。
    N072：basketId 给出时按精选篮成员过滤（复用同一导出路径/格式）。"""
    from lumirss.annotation_baskets import AnnotationBasketStore

    store = AnnotationStore(request.app.state.db)
    if payload.basketId is not None:
        if payload.entryRefs is not None or (payload.q or "").strip():
            return _invalid_response("basketId 不能与 entryRefs/q 同时使用。")
        baskets = AnnotationBasketStore(request.app.state.db)
        if not await baskets.basket_exists(payload.basketId):
            return _error_response(404, "basket_not_found", "精选篮不存在。")
        member_ids = await baskets.member_ids(payload.basketId)
        items: list[dict[str, object]] = []
        for annotation_id in sorted(member_ids):
            item = await store.get(annotation_id)
            if item is not None:
                items.append(item)
    elif payload.entryRefs is not None and len(payload.entryRefs) == 0:
        return _invalid_response("导出范围为空。")
    elif payload.entryRefs is not None:
        items = []
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
        if payload.citeBibliography:
            meta = await _entry_bibliography_meta(request.app.state.db, entry_ref)
            lines += ["", _md_escape(_bibliography_line(meta))]
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



# ---- N078 批注跨版本迁移 -------------------------------------------------------


async def _entry_content_for_version(
    request: Request, entry_ref: str, version: str
) -> str | None:
    """解析版本词对应的正文文本。current → FreshRSS 适配器实时取；
    last_known_full → N032 本地变体表（html_to_text 同一转换）。不可达
    / 变体不存在 → None（诚实拒绝，绝不拿缓存正文顶替）。"""
    from lumirss.annotation_migration import blocks_from_variant_html, validate_version

    version = validate_version(version)
    if version == "current":
        content_text = await _entry_content_text(request, entry_ref)
        return content_text
    row = await request.app.state.db.fetch_one(
        "SELECT content_html FROM entry_content_variants WHERE entry_ref = ?",
        (entry_ref,),
    )
    if row is None:
        return None
    return "\n".join(blocks_from_variant_html(str(row["content_html"] or "")))


@router.post(
    "/api/v1/annotations/migrate/preview",
    response_model=AnnotationMigratePreviewResponse,
)
async def migrate_annotations_preview(
    payload: AnnotationMigratePreviewRequest, request: Request
) -> Response:
    """N078 预览（零写入）：该文章全部批注对目标版本逐条重检（N071
    同一匹配口径）。找不到候选的批注进 unmatched（no_quote/no_match），
    绝不混入可确认列表。from/to 同版本 → 422；目标版本不可达 → 422。"""
    from lumirss.annotation_migration import (
        UnknownVersion,
        VersionContent,
        preview_items,
        validate_version,
    )

    try:
        from_version = validate_version(payload.fromVersion)
        to_version = validate_version(payload.toVersion)
    except UnknownVersion as exc:
        return _error_response(422, "unknown_annotation_version", str(exc))
    if from_version == to_version:
        return _error_response(422, "invalid_migration", "fromVersion 与 toVersion 不能相同。")
    store = AnnotationStore(request.app.state.db)
    annotations = await store.list_for_entry(payload.entryRef)
    if not annotations:
        return _error_response(404, "annotation_not_found", "该文章没有批注。")
    content_text = await _entry_content_for_version(request, payload.entryRef, to_version)
    if content_text is None:
        return _error_response(
            422,
            "entry_unavailable",
            "目标版本正文不可达（last_known_full 需保留过完整变体），无法生成迁移预览。",
        )
    matched, unmatched = preview_items(
        annotations, VersionContent(version=to_version, blocks=split_blocks(content_text))
    )
    result = AnnotationMigratePreviewResponse(
        entryRef=payload.entryRef,
        fromVersion=from_version,
        toVersion=to_version,
        matched=matched,
        unmatched=unmatched,
    )
    return JSONResponse(result.model_dump())


@router.post(
    "/api/v1/annotations/migrate/apply",
    response_model=AnnotationMigrateApplyResponse,
)
async def migrate_annotations_apply(
    payload: AnnotationMigrateApplyRequest, request: Request
) -> Response:
    """N078 应用（逐项确认）：选中项走与 N071 repair 完全相同的 rebind
    （旧锚点进 annotation_repair_log —— 撤销由该历史承载）。目标块与
    引文相似度不足 / 修复后锚点与他条冲突 → 该项 failed（reason），绝不
    覆盖既有目标批注，绝不整批中断。"""
    from lumirss.annotation_migration import UnknownVersion, validate_version

    try:
        from_version = validate_version(payload.fromVersion)
        to_version = validate_version(payload.toVersion)
    except UnknownVersion as exc:
        return _error_response(422, "unknown_annotation_version", str(exc))
    if from_version == to_version:
        return _error_response(422, "invalid_migration", "fromVersion 与 toVersion 不能相同。")
    store = AnnotationStore(request.app.state.db)
    content_text = await _entry_content_for_version(request, payload.entryRef, to_version)
    if content_text is None:
        return _error_response(
            422,
            "entry_unavailable",
            "目标版本正文不可达，无法核对迁移位置（不做缓存正文）。",
        )
    blocks = split_blocks(content_text)

    async def apply_one(item: AnnotationMigrateApplyItem):
        annotation = await store.get(item.annotationId)
        if annotation is None or annotation["entryRef"] != payload.entryRef:
            return AnnotationMigrateApplyItemResult(
                annotationId=item.annotationId, ok=False, reason="not_found"
            )
        if item.blockIndex >= len(blocks):
            return AnnotationMigrateApplyItemResult(
                annotationId=item.annotationId, ok=False, reason="block_out_of_range"
            )
        anchor = annotation["anchor"] if isinstance(annotation["anchor"], dict) else {}
        quote = str(annotation["excerpt"] or anchor.get("exact") or "").strip()
        if quote == "":
            return AnnotationMigrateApplyItemResult(
                annotationId=item.annotationId, ok=False, reason="no_quote"
            )
        bound_score = score_quote(quote, blocks[item.blockIndex])
        if bound_score < REPAIR_MIN_SCORE:
            return AnnotationMigrateApplyItemResult(
                annotationId=item.annotationId, ok=False, reason="low_score"
            )
        try:
            updated = await store.rebind(
                item.annotationId,
                block_index=item.blockIndex,
                quote=quote,
                score=round(bound_score, 4),
            )
        except AnchorHashConflict:
            # 目标锚点已被另一条批注占用 → 跳过，绝不覆盖既有批注。
            return AnnotationMigrateApplyItemResult(
                annotationId=item.annotationId, ok=False, reason="target_conflict"
            )
        if updated is None:
            return AnnotationMigrateApplyItemResult(
                annotationId=item.annotationId, ok=False, reason="not_found"
            )
        return AnnotationMigrateApplyItemResult(annotationId=item.annotationId, ok=True)

    applied: list[AnnotationMigrateApplyItemResult] = []
    failed: list[AnnotationMigrateApplyItemResult] = []
    for item in payload.items:
        result = await apply_one(item)
        if result.ok:
            applied.append(result)
        else:
            failed.append(result)
    return JSONResponse(
        AnnotationMigrateApplyResponse(applied=applied, failed=failed).model_dump()
    )
