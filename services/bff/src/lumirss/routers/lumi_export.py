"""F39 Lumi 自有数据可携带导出路由 + N010 迁出/迁入向导。"""

import json

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.lumi_data_export import build_lumi_data_export
from lumirss.lumi_data_wizard import (
    COMPONENT_LABELS,
    WizardImportError,
    apply_import,
    build_export_zip,
    collect_export_components,
    component_scope,
    new_import_session_store,
    parse_import_zip,
    preview_import,
)
from lumirss.util import utc_now

router = APIRouter()

_MAX_UPLOAD_BYTES = 32 * 1024 * 1024


@router.get("/api/v1/export/lumi-data")
async def export_lumi_data(request: Request) -> Response:
    """可携带导出：工作区/标签/书签笔记/日报配置与期刊（版本化 JSON）。

    与运维备份（全量归档）和 FreshRSS OPML 导出用途分开；不包含服务
    密钥、订阅 token、Agent 会话/审批与 Vault 内容。"""
    data = await build_lumi_data_export(request.app.state.db)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    stamp = utc_now()[:10]
    return Response(
        content=payload,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="lumirss-data-{stamp}.json"'
        },
    )


# -- N010 个人数据迁出/迁入向导 ------------------------------------------------


def _import_sessions(request: Request) -> dict[str, dict[str, object]]:
    sessions = getattr(request.app.state, "data_import_sessions", None)
    if sessions is None:
        sessions = new_import_session_store()
        request.app.state.data_import_sessions = sessions
    return sessions


def _wizard_adapters(request: Request) -> tuple[object | None, object | None]:
    """(control_adapter, read_adapter)；未绑定 RSS 源时诚实回 (None, None)。"""
    from lumirss.deps import _get_adapter_or_none

    adapter = _get_adapter_or_none(request)
    if adapter is None:
        return None, None
    from lumirss.adapters.freshrss_control import FreshRSSControlAdapter

    return FreshRSSControlAdapter(adapter), adapter


@router.get("/api/v1/export/lumi-data/scope", response_model=None)
async def export_lumi_data_scope(request: Request) -> JSONResponse:
    """导出前先看范围：每个组件的条数（来源/已读收藏需要 RSS 绑定，
    不可用时如实 available:false——绝不冒充空集是完整范围）。"""
    control, read = _wizard_adapters(request)
    components = await collect_export_components(
        request.app.state.db, control_adapter=control, read_adapter=read
    )
    return JSONResponse(
        content={"components": component_scope(components)},
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/v1/export/lumi-data.zip")
async def export_lumi_data_zip(request: Request) -> Response:
    """zip 交付（manifest.json + 每组件一个 JSON；无任何秘密）。"""
    control, read = _wizard_adapters(request)
    components = await collect_export_components(
        request.app.state.db, control_adapter=control, read_adapter=read
    )
    data = build_export_zip(components)
    stamp = utc_now()[:10]
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="lumirss-data-{stamp}.zip"'
        },
    )


@router.post("/api/v1/import/lumi-data/preview", response_model=None)
async def import_lumi_data_preview(request: Request) -> JSONResponse:
    """上传导出 zip → 各组件计数 + 冲突（已存在将被跳过）+ importId。"""
    control, _read = _wizard_adapters(request)
    body = await request.body()
    if not body:
        return _import_error("请求体为空——请上传导出 zip。")
    if len(body) > _MAX_UPLOAD_BYTES:
        return _import_error("导出包超过 32MB 上限。")
    try:
        components = parse_import_zip(body)
    except WizardImportError as exc:
        return _import_error(str(exc))
    result = await preview_import(
        request.app.state.db,
        components,
        control_adapter=control,
        store=_import_sessions(request),
    )
    return JSONResponse(
        content=result, headers={"Cache-Control": "no-store"}
    )


class ImportApplyBody(BaseModel):
    """POST /import/lumi-data/apply — 选择要合并的组件。"""

    importId: str = Field(min_length=4, max_length=64)
    components: list[str] = Field(min_length=1, max_length=16)


@router.post("/api/v1/import/lumi-data/apply", response_model=None)
async def import_lumi_data_apply(body: ImportApplyBody, request: Request) -> JSONResponse:
    """按 preview 给出的 importId 选择组件合并（跳过已存在、只加新的；
    readingState 只对当前账号已存在的引用生效）。"""
    control, read = _wizard_adapters(request)
    sessions = _import_sessions(request)
    session = sessions.get(body.importId)
    if session is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "import_session_not_found",
                    "message": "预览会话不存在或已过期——请重新上传并预览。",
                }
            },
            headers={"Cache-Control": "no-store"},
        )
    selected = [key for key in body.components if key in COMPONENT_LABELS]
    if not selected:
        return _import_error("没有可识别的组件选择。")
    try:
        result = await apply_import(
            request.app.state.db,
            session,
            selected,
            control_adapter=control,
            read_adapter=read,
        )
    except WizardImportError as exc:
        return _import_error(str(exc))
    sessions.pop(body.importId, None)  # 一次性消费
    return JSONResponse(content=result, headers={"Cache-Control": "no-store"})


def _import_error(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": {"type": "invalid_import", "message": message}},
        headers={"Cache-Control": "no-store"},
    )
