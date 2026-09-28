"""N098 音频生成缓存路由 — 服务端 TTS 合成 + 缓存管理（全部 per-user）。

- POST   /api/v1/tts/synthesize      {text ≤2000, voice} → audio/mpeg；
                                      命中缓存 X-Cache: hit（零外部请求），
                                      未命中恰一次 provider 调用并缓存；
- GET    /api/v1/tts/cache           缓存清单（size/date）+ 总量/上限；
- DELETE /api/v1/tts/cache/{id}      删一条（own only —— per-user 库保证）；
- DELETE /api/v1/tts/cache           清空本人缓存。

诚实边界：用户未配置 TTS 能力（purpose=tts 无 base_url+model+key）时
synthesize 返回 409 tts_not_configured —— UI 必须如实说明「只在配置了
TTS provider 后可用」，绝不假装能合成。
"""

import asyncio
import contextlib

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from lumirss.config import LumiSettings
from lumirss.tts_service import (
    DEFAULT_VOICE,
    TtsCacheStore,
    TtsNotConfigured,
    TtsTextInvalid,
    TtsUpstreamError,
    synthesize,
)

router = APIRouter()


class TtsSynthesizeRequest(BaseModel):
    """POST /api/v1/tts/synthesize body。"""

    model_config = {"extra": "forbid"}

    text: str = Field(min_length=1, max_length=2000)
    voice: str = Field(default=DEFAULT_VOICE, max_length=100)

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


async def _tts_provider_config(request: Request):
    """purpose=tts → 已解析 provider 配置（经既有 profile 系统；key 服务端
    only，绝不序列化出边界）。未配置时返回 configured=False 的对象。"""
    from lumirss.deps import _get_ai_profile_store, _get_ai_settings_store
    from lumirss.tts_service import TtsProviderConfig

    profile_store = _get_ai_profile_store(request)
    settings = await _get_ai_settings_store(request).load()
    effective = await profile_store.effective_config(
        "tts", settings, LumiSettings().AI_API_KEY.get_secret_value()
    )
    return TtsProviderConfig(
        base_url=effective.base_url,
        model=effective.model,
        api_key=effective.api_key or "",
    )


async def _await_client_disconnect(request: Request) -> bool:
    """FIX-147：轮询客户端断开。POST body 已被 FastAPI 消费，此后
    receive 只会再给 http.disconnect；Starlette 的 is_disconnected 是
    非阻塞即时检查（anyio 即时取消域），轮询即安全。"""
    while True:
        if await request.is_disconnected():
            return True
        await asyncio.sleep(0.2)


@router.post("/api/v1/tts/synthesize")
async def tts_synthesize(payload: TtsSynthesizeRequest, request: Request) -> Response:
    """合成语音（缓存优先）。X-Cache: hit | miss 诚实区分来源。

    FIX-147：客户端中途弃合成（切文/退出页面 → 连接断开）即取消服务端
    合成任务——上游 provider 计费调用与 BFF 任务不因断开空转到
    TTS_TIMEOUT_S；弃合成不落缓存行（合成从未完整发生，无半途结果可
    缓存）。上游失败路径零缓存行 + 响应流必关（FIX-249 finally 边界）。
    """
    config = await _tts_provider_config(request)
    work = asyncio.ensure_future(
        synthesize(
            request.app.state.db,
            request.app.state.http_client,
            config,
            text=payload.text,
            voice=payload.voice,
        )
    )
    abandoned = asyncio.ensure_future(_await_client_disconnect(request))
    try:
        done, _pending = await asyncio.wait(
            {work, abandoned}, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        abandoned.cancel()
    if work not in done:
        # 断开先到：取消合成（_call_provider 的 finally 关闭上游流），
        # 不写缓存行；应答无人接收，最小收尾即可。
        work.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await work
        return Response(status_code=204)
    try:
        audio, cache_hit = work.result()
    except TtsNotConfigured as exc:
        return _error(409, "tts_not_configured", str(exc))
    except TtsTextInvalid as exc:
        return _error(422, "tts_text_invalid", str(exc))
    except TtsUpstreamError as exc:
        return _error(502, "tts_upstream_error", str(exc))
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"X-Cache": "hit" if cache_hit else "miss", "Cache-Control": "no-store"},
    )


@router.get("/api/v1/tts/cache")
async def tts_cache_list(request: Request) -> JSONResponse:
    """缓存清单（size/date；总量与 50MB 上限如实给出）。"""
    store = TtsCacheStore(request.app.state.db)
    return JSONResponse(await store.list_entries())


@router.delete("/api/v1/tts/cache/{entry_id}", status_code=204)
async def tts_cache_delete(entry_id: str, request: Request) -> Response:
    """删除一条缓存（own only：per-user 库中只存在本人的行，他人 id
    天然 404）。"""
    deleted = await TtsCacheStore(request.app.state.db).delete_one(entry_id)
    if not deleted:
        return _error(404, "tts_cache_not_found", "缓存条目不存在。")
    return Response(status_code=204)


@router.delete("/api/v1/tts/cache", status_code=200)
async def tts_cache_clear(request: Request) -> JSONResponse:
    """清空本人全部 TTS 缓存（返回真实删除数）。"""
    removed = await TtsCacheStore(request.app.state.db).delete_all()
    return JSONResponse({"removed": removed})
