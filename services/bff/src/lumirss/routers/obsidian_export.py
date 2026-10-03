"""R07 服务端受限写入导出路由 — 所有内容来源可剪藏到 Obsidian 仓库。

- POST /api/v1/obsidian/export ``{refs, include{summary,translation,
  annotations}}`` → 逐项结果（written | exists | failed + 原因）
- GET  /api/v1/obsidian/export/status → 目标目录、今日用量、最近导出
- GET/PUT /api/v1/obsidian/export/settings → 导出子目录偏好

鉴权与作用域：用户级（与 devices / handoff-log 同一惯例——任何登录
账户管理自己的导出，不设 owner 门槛）。导出根是部署上独立挂载的
服务端可写目录（``LUMIRSS_OBSIDIAN_EXPORT_DIR``，生产 overlay 挂
``/vault-export``，rw；只读投影的 ``/vault`` 挂载不受影响）；目录内
``<subdir>/<user_id>/`` 按账户隔离。写面硬保证（containment / 原子
且绝不覆盖 / content-id 幂等 / 1MB·50 条·每日 64MB 有界）全部在
:mod:`lumirss.obsidian_export`，本路由只做内容收集与编组。

内容收集：ItemRef → 各内容域既有读路径（导出要正文，不是卡片投影）。
当前可达：rss entry（adapter）、bookmark、clip、snapshot（文字层，
未建则从快照 HTML 现场提取，只读）、inbox item（api_source article）。
newsletter_item 的正文存于 FreshRSS（ADR 0004 无库侧正文）、digest
issue 与 mail 原文尚未接入 ItemRef registry —— 一律如实 failed，
绝不臆造正文；obsidian_note 本就在 Vault 中，如实拒绝导出。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from lumirss.itemref import InvalidItemRef
from lumirss.obsidian_export import (
    ExportBatchTooLarge,
    ExportPayload,
    ExportSubdirInvalid,
    ObsidianExportService,
)

router = APIRouter()


# ---- 请求 / 响应模型（router-local，同 new300 等新路由惯例） ----------


class ExportInclude(BaseModel):
    """可选附加分区：AI 摘要 / 译文 / 批注（存在才写，缺失诚实省略）。"""

    model_config = ConfigDict(extra="forbid")

    summary: bool = False
    translation: bool = False
    annotations: bool = False


class ObsidianExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refs: list[str] = Field(min_length=1, max_length=50)
    include: ExportInclude = Field(default_factory=ExportInclude)


class ObsidianExportSubdirUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subdir: str


# ---- 服务与身份 -------------------------------------------------------


def _export_service(request: Request) -> ObsidianExportService:
    """每次请求现建（无跨请求状态；db 由中间件路由到当前用户库）。"""
    from lumirss.config import LumiSettings

    return ObsidianExportService(
        request.app.state.db,
        export_dir=LumiSettings().LUMIRSS_OBSIDIAN_EXPORT_DIR,
    )


def _require_user(request: Request) -> tuple[dict[str, str] | None, JSONResponse | None]:
    """服务端派生身份（SessionAuthMiddleware 绑定的 user 上下文）；缺失即 401。

    与 routers/obsidian.py 的 owner 判定同源（principal_of），per-user
    数据面统一以 user_scope 的 ContextVar 为准——两条通道（会话/机器
    token）都由中间件绑定，测试 harness（new201_210_harness）也走它。
    """
    from lumirss.user_scope import NoUserContextError, principal_of, require_user_id

    try:
        user_id = require_user_id()
    except NoUserContextError:
        return None, JSONResponse(
            status_code=401,
            content={
                "error": {"type": "unauthorized", "message": "Login required."}
            },
            headers={"Cache-Control": "no-store"},
        )
    principal = principal_of(request.scope) or {}
    return {"user_id": user_id, "username": str(principal.get("username", ""))}, None


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


# ---- 内容收集（ItemRef → ExportPayload） ------------------------------


class _CollectFailed(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


async def _ai_section(db: Any, entry_key: str, include: ExportInclude) -> dict[str, Any]:
    """已生成的 AI 摘要 / 译文（只读已落库的成功行；绝不触发上游生成）。"""
    section: dict[str, Any] = {}
    if include.summary:
        row = await db.fetch_one(
            "SELECT summary_text FROM ai_summaries WHERE entry_ref = ? AND status = 'success'"
            " ORDER BY updated_at DESC LIMIT 1",
            (entry_key,),
        )
        if row is not None and str(row["summary_text"] or "").strip():
            section["summary"] = str(row["summary_text"])
    if include.translation:
        row = await db.fetch_one(
            "SELECT translated_title, translated_text FROM ai_translations"
            " WHERE entry_ref = ? AND status = 'success'"
            " ORDER BY updated_at DESC LIMIT 1",
            (entry_key,),
        )
        if row is not None and str(row["translated_text"] or "").strip():
            section["translation_title"] = str(row["translated_title"] or "")
            section["translation_text"] = str(row["translated_text"])
    return section


async def _annotation_section(
    db: Any, annotation_ref: str, include: ExportInclude
) -> list[dict[str, str]]:
    """批注清单（含段落锚点 → 阅读器回跳链接；公开基底配置时为绝对链）。"""
    if not include.annotations:
        return []
    from lumirss.annotation_store import AnnotationStore
    from lumirss.config import LumiSettings

    rows = await AnnotationStore(db).list_for_entry(annotation_ref)
    base = LumiSettings().LUMIRSS_PUBLIC_URL.strip().rstrip("/")
    rendered: list[dict[str, str]] = []
    for row in rows:
        anchor = row.get("anchor")
        para = ""
        if isinstance(anchor, dict):
            para = str(anchor.get("paraId") or "")
        query = f"entry={annotation_ref}" + (f"&para={para}" if para else "")
        link = f"/reader?{query}"
        if base:
            link = f"{base}{link}"
        rendered.append(
            {
                "quote": str(row.get("excerpt") or "").strip(),
                "note": str(row.get("note") or "").strip(),
                "link": link,
            }
        )
    return rendered


async def _collect_rss(request: Request, ref: str, key: str, include: ExportInclude) -> ExportPayload:
    """rss 条目：与阅读页同一 adapter 读路径；正文取安全纯文本渲染。"""
    from lumirss.adapters.freshrss import ConfigError, EntryNotFound
    from lumirss.deps import _get_adapter
    from lumirss.entryref import decode_entry_ref

    try:
        detail = await _get_adapter(request).get_entry(decode_entry_ref(key))
    except ConfigError as exc:
        raise _CollectFailed("upstream_unavailable", "FreshRSS 未配置，无法读取该条目。") from exc
    except EntryNotFound as exc:
        raise _CollectFailed("not_found", "条目不存在或已从上游删除。") from exc
    sections = await _ai_section(request.app.state.db, key, include)
    annotations = await _annotation_section(
        request.app.state.db, key, include
    )
    return ExportPayload(
        ref=ref,
        source_type="rss",
        title=str(detail.title or ""),
        source_name=str(detail.feedTitle or ""),
        url=str(detail.url or ""),
        author=detail.author,
        published=detail.publishedAt or detail.crawledAt,
        body_text=str(detail.contentText or "").strip() or None,
        summary=sections.get("summary"),
        translation_title=sections.get("translation_title"),
        translation_text=sections.get("translation_text"),
        annotations=tuple(annotations),
    )


async def _collect_library(
    request: Request, ref: str, key: str, include: ExportInclude
) -> ExportPayload:
    """library 域逐 kind 分派（ADR 0004；与 source registry 同一 kinds 集）。"""
    from lumirss.deps import _get_clip_store, _get_inbox_store, _get_library_store

    library = _get_library_store(request)
    kind = await library.get_kind(key)
    db = request.app.state.db
    if kind == "bookmark":
        view = await library.get_bookmark(key)
        if view is None:
            raise _CollectFailed("not_found", "收藏不存在。")
        # 书签没有抓取正文：note 即笔记正文；空 note → 「未抓取全文」路径。
        return ExportPayload(
            ref=ref,
            source_type="bookmark",
            title=str(view.title or ""),
            source_name="书签",
            url=str(view.url or ""),
            body_text=str(view.note or "").strip() or None,
        )
    if kind == "clip":
        clip = await _get_clip_store(request).get_clip(key)
        if clip is None:
            raise _CollectFailed("not_found", "剪藏不存在。")
        return ExportPayload(
            ref=ref,
            source_type="clip",
            title=str(clip.title or ""),
            source_name="剪藏",
            url=str(clip.url or ""),
            author=str(clip.byline or "").strip() or None,
            body_text=str(clip.content_text or "").strip() or None,
        )
    if kind == "snapshot":
        row = await db.fetch_one(
            "SELECT uuid, mime, url, created_at FROM library_assets WHERE item_uuid = ?",
            (key,),
        )
        if row is None:
            raise _CollectFailed("not_found", "快照不存在。")
        body = await _snapshot_readable_text(request, str(row["uuid"]))
        return ExportPayload(
            ref=ref,
            source_type="snapshot",
            title=f"快照 · {row['mime']}",
            source_name="快照",
            url=str(row["url"] or ""),
            body_text=body or None,
        )
    if kind == "api_item":
        inbox = await _get_inbox_store(request).get_item(key)
        if inbox is None:
            raise _CollectFailed("not_found", "收件箱条目不存在。")
        return ExportPayload(
            ref=ref,
            source_type="api_source",
            title=str(inbox["title"] or ""),
            source_name=f"Inbox · {inbox['sourceName']}",
            url=str(inbox["url"] or ""),
            author=str(inbox.get("author") or "").strip() or None,
            published=inbox.get("publishedAt"),
            body_text=str(inbox.get("contentText") or "").strip() or None,
        )
    if kind == "obsidian_note":
        raise _CollectFailed("unsupported", "该笔记本身就在 Vault 中，无需导出。")
    if kind == "newsletter_item":
        raise _CollectFailed(
            "unsupported",
            "newsletter 条目的正文存于 FreshRSS（库侧无正文），暂不支持导出。",
        )
    if kind is None:
        raise _CollectFailed("not_found", "内容不存在（或已删除）。")
    raise _CollectFailed("unsupported", "该内容类型暂不支持导出。")


async def _snapshot_readable_text(request: Request, asset_uuid: str) -> str:
    """快照可读正文：优先已建文字层；未建则从快照 HTML 现场提取（只读）。

    快照字节保持不变——提取是纯读（new314 的 build 才会落文字层表，
    导出路径绝不写投影面）。
    """
    from lumirss.new314_snapshot_text_layer import extract_text_blocks

    db = request.app.state.db
    rows = await db.fetch_all(
        "SELECT text FROM snapshot_text_layers WHERE asset_uuid = ?"
        " ORDER BY seq ASC LIMIT 400",
        (asset_uuid,),
    )
    if rows:
        return "\n\n".join(str(row["text"]) for row in rows)
    from lumirss.deps import _get_snapshot_store
    from lumirss.library_assets import AssetNotFound

    try:
        data = await _get_snapshot_store(request).read_bytes(asset_uuid)
    except AssetNotFound:
        return ""
    try:
        html_text = data.decode("utf-8")
    except UnicodeDecodeError:
        html_text = data.decode("utf-8", errors="replace")
    return "\n\n".join(
        str(block["text"]) for block in extract_text_blocks(html_text)
    )


async def _collect_payload(
    request: Request, ref: str, include: ExportInclude
) -> ExportPayload:
    from lumirss.itemref import parse_item_ref

    parsed = parse_item_ref(ref)  # 无效 ref → InvalidItemRef → 逐项 failed
    if parsed.domain == "rss":
        return await _collect_rss(request, ref, parsed.key, include)
    if parsed.domain == "library":
        return await _collect_library(request, ref, parsed.key, include)
    raise _CollectFailed("unsupported", "该内容类型暂不支持导出。")


# ---- 路由 -------------------------------------------------------------


@router.post("/api/v1/obsidian/export")
async def export_to_obsidian(
    payload: ObsidianExportRequest, request: Request
) -> JSONResponse:
    """逐条导出到服务端导出根；返回与输入同序的逐项结果。

    同一批内的重复 ref 去重（同 content-id 同内容本就幂等，去重只是
    少一次台账行）；收集失败与写入失败都不中断整批。
    """
    principal, guard = _require_user(request)
    if principal is None:
        assert guard is not None
        return guard
    service = _export_service(request)
    unique_refs: list[str] = []
    seen: set[str] = set()
    for ref in payload.refs:
        if ref not in seen:
            seen.add(ref)
            unique_refs.append(ref)

    collected: list[tuple[str, ExportPayload | None, dict[str, Any] | None]] = []
    for ref in unique_refs:
        try:
            item = await _collect_payload(request, ref, payload.include)
            collected.append((ref, item, None))
        except _CollectFailed as exc:
            collected.append(
                (
                    ref,
                    None,
                    {
                        "ref": ref,
                        "status": "failed",
                        "path": None,
                        "reason": exc.reason,
                        "contentId": None,
                        "bytes": 0,
                        "message": str(exc),
                    },
                )
            )
        except InvalidItemRef:
            # 单条 ref 不合法 = 单条 failed，绝不中断整批。
            collected.append(
                (
                    ref,
                    None,
                    {
                        "ref": ref,
                        "status": "failed",
                        "path": None,
                        "reason": "invalid_ref",
                        "contentId": None,
                        "bytes": 0,
                        "message": "ItemRef 不合法。",
                    },
                )
            )
    payloads = [item for _, item, _ in collected if item is not None]
    try:
        exported = await service.export_batch(
            payloads, user_id=principal["user_id"]
        )
    except ExportBatchTooLarge as exc:
        return _error(422, "invalid_export_batch", str(exc))
    by_ref = {result["ref"]: result for result in exported}
    items: list[dict[str, Any]] = []
    for ref, item, failure in collected:
        if failure is not None:
            items.append(failure)
        elif item is not None and (result := by_ref.get(ref)) is not None:
            items.append(result)
    counts = {
        "written": sum(1 for i in items if i["status"] == "written"),
        "exists": sum(1 for i in items if i["status"] == "exists"),
        "failed": sum(1 for i in items if i["status"] == "failed"),
    }
    return JSONResponse({"items": items, **counts})


@router.get("/api/v1/obsidian/export/status")
async def obsidian_export_status(request: Request) -> JSONResponse:
    """导出目标目录、今日用量、每日上限、最近导出台账（per-user）。"""
    principal, guard = _require_user(request)
    if principal is None:
        assert guard is not None
        return guard
    service = _export_service(request)
    return JSONResponse(
        await service.status(user_id=principal["user_id"])
    )


@router.get("/api/v1/obsidian/export/settings")
async def get_obsidian_export_settings(request: Request) -> JSONResponse:
    principal, guard = _require_user(request)
    if principal is None:
        assert guard is not None
        return guard
    service = _export_service(request)
    return JSONResponse({"subdir": await service.get_subdir()})


@router.put("/api/v1/obsidian/export/settings")
async def set_obsidian_export_settings(
    payload: ObsidianExportSubdirUpdate, request: Request
) -> JSONResponse:
    """设置导出子目录（vault 导出根内的相对子路径，默认 LumiRSS）。"""
    principal, guard = _require_user(request)
    if principal is None:
        assert guard is not None
        return guard
    service = _export_service(request)
    try:
        subdir = await service.set_subdir(payload.subdir)
    except ExportSubdirInvalid as exc:
        return _error(422, "invalid_export_subdir", str(exc))
    return JSONResponse({"subdir": subdir})
