"""FIX-147 — TTS 合成/缓存生命周期：客户端弃合成即取消，失败不落缓存。

BFF-side 判定（播放/暂停/切文/退出页面的音频资源泄漏，服务端等价面）：

1. 中途弃合成（切文/退出页面 → HTTP 断开）：synthesis 路由是非流式
   响应，Starlette 对非流式 handler 不因 http.disconnect 取消任务——
   旧行为是 handler 继续把上游 provider 调用空转到 TTS_TIMEOUT_S=60s
   （计费面持续运行、任务与上游连接被占满整个窗口）。要求与 FIX-365
   的 SSE 等价：断开即取消（任务取消 → 上游流 finally aclose），
   且弃合成不落缓存行（合成从未完成，半途结果不缓存）。
2. 上游失败（mid-stream 错误）：绝不写缓存行（只缓存完整合成结果），
   上游响应流必须被 aclose（FIX-249 的 finally 边界）。
3. 临时文件：TTS 路径零 tempfile——音频全程内存字节且封顶
   MAX_AUDIO_BYTES=5MB（源码 grep 佐证，无 I/O 句柄可泄漏）。

测试 1 用 raw-ASGI 仿真 http.disconnect（TestClient/httpx
ASGITransport 不会向 app 发 http.disconnect，无法仿真断开）。
无真实秘密；provider 全部替身。
"""

import asyncio
import json
import time

import pytest

from lumirss.storage import Database
from lumirss.tts_service import (
    TtsProviderConfig,
    TtsUpstreamError,
    synthesize,
)

CONFIG = TtsProviderConfig(
    base_url="https://tts.example/v1", model="tts-1", api_key="sk-test"
)


# ---------------------------------------------------------------------------
# 测试 1：raw-ASGI 弃合成 → 取消传播
# ---------------------------------------------------------------------------


class HangingProvider:
    """app.state.http_client 替身：/audio/speech 挂起直到被取消。"""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    def build_request(self, *args, **kwargs):
        return object()  # 对 _call_provider 不透明

    async def send(self, request, stream: bool = False):
        self.started.set()
        try:
            await asyncio.sleep(3600)  # 挂起：只有取消能打断
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def aclose(self) -> None:  # lifespan shutdown 会调用
        return None


def _scope(method: str, path: str, body: bytes) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("testclient", 123),
        "server": ("testserver", 80),
        "extensions": {},
    }


async def _asgi_post_json(app, path: str, payload: dict, disconnect: asyncio.Event):
    """Raw-ASGI POST：body 一次投递；其后 receive 在 disconnect 置位后
    返回 http.disconnect（真实客户端断开语义）。"""
    body = json.dumps(payload).encode()

    async def receive():
        if body is not None and not receive.sent_body:  # type: ignore[attr-defined]
            receive.sent_body = True  # type: ignore[attr-defined]
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    receive.sent_body = False  # type: ignore[attr-defined]

    status: dict[str, int] = {}

    async def send(message):
        if message["type"] == "http.response.start":
            status["code"] = message["status"]

    await app(_scope("POST", path, body), receive, send)
    return status.get("code")


async def _drive_abandon(app) -> tuple[HangingProvider, int | None, float]:
    """前提：_tts_provider_config 已被 monkeypatch 为已配置替身。"""
    provider = HangingProvider()
    app.state.http_client = provider

    disconnect = asyncio.Event()
    task = asyncio.ensure_future(
        _asgi_post_json(
            app, "/api/v1/tts/synthesize", {"text": "弃合成文本", "voice": "alloy"}, disconnect
        )
    )
    await asyncio.wait_for(provider.started.wait(), timeout=10)
    # 合成正挂在 provider 调用上——模拟客户端切文/退出页面断开。
    disconnect.set()
    started = time.monotonic()
    status = await asyncio.wait_for(task, timeout=10)
    elapsed = time.monotonic() - started
    return provider, status, elapsed


def test_client_abandon_mid_synthesis_cancels_provider_and_skips_cache(monkeypatch):
    """断开 → 上游 provider 调用被取消（<5s，非 60s 空转），弃合成不落缓存行。"""

    async def scenario():
        from lumirss.main import app

        async with app.router.lifespan_context(app):
            from lumirss.accounts_store import AccountsStore
            from lumirss.user_scope import user_context

            owners = await AccountsStore(app.state.control_db).list_users(limit=10)
            owner_id = next(str(row["id"]) for row in owners if row["role"] == "owner")
            with user_context(owner_id):
                import lumirss.routers.tts as tts_router

                class FakeProviderConfig:
                    base_url = CONFIG.base_url
                    model = CONFIG.model
                    api_key = CONFIG.api_key

                    @property
                    def configured(self):
                        return True

                async def fake_config(request):
                    return FakeProviderConfig()

                monkeypatch.setattr(tts_router, "_tts_provider_config", fake_config)

                provider, status, elapsed = await _drive_abandon(app)
                # 若取消未传播，handler 要等 3600s 挂起被 10s wait_for 打断。
                assert elapsed < 5, f"断开后 handler 仍空转 {elapsed:.1f}s"
                assert provider.cancelled is True, "上游 provider 调用未被取消"
                assert status == 204  # 弃合成的应答无人接收，最小收尾
                # 弃合成绝不落缓存行（合成从未完整发生）。
                from lumirss.tts_service import TtsCacheStore

                assert (await TtsCacheStore(app.state.db).list_entries())["count"] == 0

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# 测试 2：上游 mid-stream 失败 → 不落缓存行 + 上游流关闭
# ---------------------------------------------------------------------------


class _BrokenStreamResponse:
    status_code = 200

    def __init__(self) -> None:
        self.closed = False

    async def aiter_bytes(self):
        yield b"partial-mp3"
        raise RuntimeError("mid-stream boom")

    async def aclose(self) -> None:
        self.closed = True


class BrokenStreamClient:
    """200 后 mid-stream 断裂的 provider 替身（真实 httpx 流式接口形状）。"""

    def __init__(self) -> None:
        self.response = _BrokenStreamResponse()

    def build_request(self, *args, **kwargs):
        return object()

    async def send(self, request, stream: bool = False):
        return self.response


@pytest.fixture()
def db(tmp_path):
    async def make():
        database = Database(str(tmp_path / "lumi.sqlite"))
        await database.migrate()
        return database

    return asyncio.run(make())


def test_provider_failure_midstream_writes_no_cache_row_and_closes_stream(db):
    """上游 mid-stream 失败 → TtsUpstreamError、缓存零行、响应流已 aclose。"""
    from lumirss.tts_service import TtsCacheStore

    http = BrokenStreamClient()
    with pytest.raises(TtsUpstreamError):
        asyncio.run(synthesize(db, http, CONFIG, text="失败文本", voice="alloy"))
    assert http.response.closed is True, "上游响应流未被关闭（连接泄漏）"
    listing = asyncio.run(TtsCacheStore(db).list_entries())
    assert listing["count"] == 0, "失败的半途合成不得写入缓存行"
    assert listing["totalBytes"] == 0
