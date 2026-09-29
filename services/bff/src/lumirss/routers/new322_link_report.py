"""NEW-322 链接解析报告路由 — 范围报告 + 逐项纠正。

- POST   /api/v1/obsidian/link-report                    {noteUuids?: []} → 报告
- GET    /api/v1/obsidian/link-report/corrections        纠正列表
- PUT    /api/v1/obsidian/link-report/corrections        {noteUuid, raw, targetUuid}
- DELETE /api/v1/obsidian/link-report/corrections?noteUuid=&raw=

只读报告 + 用户显式纠正导入映射；绝不写 Vault。owner 门槛与主
Obsidian 面一致（O168）。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.new322_link_report import LinkReportStore
from lumirss.routers.obsidian import _require_owner

router = APIRouter()


def _store(request: Request) -> LinkReportStore:
    return LinkReportStore(request.app.state.db)


@router.post("/api/v1/obsidian/link-report")
async def build_link_report(payload: dict[str, Any], request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    note_uuids = payload.get("noteUuids")
    scope = note_uuids if isinstance(note_uuids, list) else None
    return JSONResponse(await _store(request).build_report(scope))


@router.get("/api/v1/obsidian/link-report/corrections")
async def list_link_corrections(request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    return JSONResponse({"corrections": await _store(request).list_corrections()})


@router.put("/api/v1/obsidian/link-report/corrections", status_code=200)
async def put_link_correction(payload: dict[str, Any], request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    try:
        correction = await _store(request).put_correction(
            str(payload.get("noteUuid") or ""),
            str(payload.get("raw") or ""),
            str(payload.get("targetUuid") or ""),
        )
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "note_not_found",
                    "message": "源笔记不存在（投影中没有该 uuid）。",
                }
            },
        )
    except LookupError:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "type": "invalid_correction_target",
                    "message": "纠正目标笔记不存在。",
                }
            },
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_correction", "message": str(exc)}},
        )
    return JSONResponse(correction)


@router.delete("/api/v1/obsidian/link-report/corrections")
async def delete_link_correction(request: Request, noteUuid: str = "", raw: str = "") -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    deleted = await _store(request).delete_correction(noteUuid, raw)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "correction_not_found", "message": "纠正记录不存在。"}
            },
        )
    return JSONResponse({"deleted": True})
