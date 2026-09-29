"""NEW-284 简报缺刊诊断路由 — 生成尝试台账（failed → ok 轨迹）。"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.new284_diagnostics import AttemptStore

router = APIRouter()


@router.get("/api/v1/briefings/attempts")
async def list_attempts(request: Request, limit: int = 20) -> JSONResponse:
    rows = await AttemptStore(request.app.state.db).list_attempts(limit=limit)
    return JSONResponse(
        {
            "attempts": rows,
            "count": len(rows),
            "honestyNote": (
                "生成失败绝不呈现为空白成功页：每次尝试的阶段与缺失输入"
                "都在此留痕，补输入后重跑即可。"
            ),
        }
    )
