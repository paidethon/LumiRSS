"""NEW-381..390 长期保存与格式互通 —— 路由层公共门槛。

会话模式下要求已登录（任意成员，feature 面是个人库，per-user 库
天然隔离）；非会话模式（单用户）直接放行——与 new341 同口径。
"""

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

# 文本类导入（RDF / RIS / WARC 档案）的读取上限：2MiB 文本、3MiB 档案，
# 均低于全局请求体中间件的 4MiB 硬上限。
MAX_PREVIEW_BYTES = 2 * 1024 * 1024
MAX_WARC_BYTES = 3 * 1024 * 1024


async def require_preservation_user(request: Request) -> str | None:
    """会话模式下返回 401 响应（未登录）或 None（放行）。"""
    from lumirss.config import LumiSettings
    from lumirss.routers.auth import _current_user_id

    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return None
    user_id = await _current_user_id(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={
                "error": {"type": "session_required", "message": "Login required."}
            },
            headers={"Cache-Control": "no-store"},
        )
    return None


def error_response(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
        headers={"Cache-Control": "no-store"},
    )


async def read_limited_text(
    request: Request, max_bytes: int
) -> str | JSONResponse:
    """读取原始请求体文本（上限内），与既有导入端点同口径。"""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            return error_response(
                400,
                "invalid_import_file",
                f"导入文件超过 {max_bytes // (1024 * 1024)}MiB 上限。",
            )
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return error_response(400, "invalid_import_file", "导入文件不是有效的 UTF-8 文本。")


def no_store(payload: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})
