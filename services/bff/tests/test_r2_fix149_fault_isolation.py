"""FIX-149 — AI/翻译/TTS 配置了但不可达时，核心 RSS 阅读不被阻断。

故障注入（全部在共享 http_client 层挂起——三个能力经同一
`app.state.http_client` 构建 provider/deps._provider_factory_for +
tts_service._call_provider，一处注入即同时命中）：

- AI 摘要 POST /entries/{ref}/summary；
- 翻译 POST /entries/{ref}/translation/segments/generate；
- TTS POST /tts/synthesize。

三者全部挂在 provider 调用中时，核心阅读面必须照常响应（列表/详情/
读星/搜索），逐请求 5s 死线——证明没有跨能力全局锁、事件循环阻塞或
共享线程耦合；挂起能力被取消后阅读面依旧健康（无未处理拒绝把路由
带坏）。Raw-ASGI 驱动（TestClient 同步 portal 无法并发挂起）。
"""

import asyncio
import json
import time

from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.models import EntryDetail, EntryListItem, EntryPage

REF = encode_entry_ref("tag:google.com,2005:reader/item/0000000000000049")

_DETAIL = EntryDetail(
    entryRef=REF,
    title="核心阅读条目",
    feedTitle="测试源",
    url="http://example.com/a",
    publishedAt="2026-09-01T00:00:00Z",
    read=False,
    starred=False,
    contentText="正文纯文本。",
    contentHtml="<p>正文纯文本。</p>",
)

_LIST = EntryPage(
    items=[
        EntryListItem(
            entryRef=REF,
            title="核心阅读条目",
            feedTitle="测试源",
            author=None,
            url="http://example.com/a",
            publishedAt="2026-09-01T00:00:00Z",
            read=False,
            starred=False,
        )
    ],
    upstreamContinuation=None,
)


class FakeCoreAdapter:
    """核心阅读数据面替身：列表/详情/读写状态（零上游）。"""

    def __init__(self) -> None:
        self.writes: list[tuple] = []

    async def list_feeds(self):
        return []

    async def list_entries(self, **kwargs):
        return _LIST

    async def get_entry(self, item_id: str) -> EntryDetail:
        return _DETAIL

    async def set_entry_state(self, item_id: str, *, read=None, starred=None):
        self.writes.append((item_id, read, starred))


class HungHttpClient:
    """共享 http_client 替身：任何外呼（post/send）都挂起（上游黑洞）。"""

    def __init__(self) -> None:
        self.events: list[asyncio.Event] = []

    def build_request(self, *args, **kwargs):
        return object()  # 对调用方不透明

    def _hang_point(self) -> asyncio.Event:
        event = asyncio.Event()
        self.events.append(event)
        event.set()  # 标记“已进入挂起的上游调用”
        return event

    async def post(self, *args, **kwargs):
        self._hang_point()
        await asyncio.sleep(3600)  # 只有取消能打断

    async def send(self, request, stream: bool = False):
        self._hang_point()
        await asyncio.sleep(3600)

    async def aclose(self) -> None:
        return None


def _scope(method: str, path: str, query: str, body: bytes) -> dict:
    headers = [(b"host", b"testserver")]
    if body:
        headers += [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": headers,
        "client": ("testclient", 123),
        "server": ("testserver", 80),
        "extensions": {},
    }


async def _asgi_request(
    app, method: str, path: str, payload: dict | None = None, query: str = ""
) -> tuple[int | None, bytes]:
    """Raw-ASGI 单请求：客户端保持连接（receive 阻塞，不发 disconnect）。"""
    body = json.dumps(payload).encode() if payload is not None else b""
    state = {"sent": False}
    hang = asyncio.Event()

    async def receive():
        if not state["sent"]:
            state["sent"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        await hang.wait()  # 客户端一直连着——永不断开
        return {"type": "http.disconnect"}

    status: dict[str, int] = {}
    chunks: list[bytes] = []

    async def send(message):
        if message["type"] == "http.response.start":
            status["code"] = message["status"]
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    await app(_scope(method, path, query, body), receive, send)
    return status.get("code"), b"".join(chunks)


async def _scenario(monkeypatch) -> None:
    from lumirss.accounts_store import AccountsStore
    from lumirss.user_scope import user_context

    async with app.router.lifespan_context(app):
        owners = await AccountsStore(app.state.control_db).list_users(limit=10)
        owner_id = next(str(row["id"]) for row in owners if row["role"] == "owner")
        with user_context(owner_id):
            # 1. 配置 AI（summary/translation/tts 默认链共用：baseUrl+model+key）
            status, _ = await _asgi_request(
                app,
                "PUT",
                "/api/v1/settings/ai",
                {"baseUrl": "https://ai.example.com/v1", "model": "model-x"},
            )
            assert status == 200
            status, _ = await _asgi_request(
                app, "PUT", "/api/v1/settings/ai/key", {"value": "sk-fix149-test"}
            )
            assert status == 204

            # 2. 注入：共享 http_client 挂起 + 阅读数据面替身
            hung = HungHttpClient()
            monkeypatch.setattr(app.state, "http_client", hung, raising=False)
            adapter = FakeCoreAdapter()
            monkeypatch.setattr(app.state, "freshrss_adapter", adapter, raising=False)

            # 3. 三个能力全部发起 → 全部挂进 provider 调用
            tasks = {
                "summary": asyncio.ensure_future(
                    _asgi_request(app, "POST", f"/api/v1/entries/{REF}/summary")
                ),
                "translation": asyncio.ensure_future(
                    _asgi_request(
                        app,
                        "POST",
                        f"/api/v1/entries/{REF}/translation/segments/generate",
                        {"blocks": [{"index": 0, "text": "需要翻译的段落"}]},
                    )
                ),
                "tts": asyncio.ensure_future(
                    _asgi_request(
                        app, "POST", "/api/v1/tts/synthesize", {"text": "朗读文本"}
                    )
                ),
            }
            deadline = time.monotonic() + 10
            while len(hung.events) < 3:
                assert time.monotonic() < deadline, "三个能力未全部进入上游调用"
                await asyncio.sleep(0.05)

            # 4. 核心阅读面在三个能力全部挂起时照常响应（逐请求 5s 死线）
            started = time.monotonic()
            status, _ = await asyncio.wait_for(
                _asgi_request(app, "GET", "/api/v1/entries"), timeout=5
            )
            assert status == 200, "entries list 被挂起的 AI/TTS 阻断"
            status, body = await asyncio.wait_for(
                _asgi_request(app, "GET", f"/api/v1/entries/{REF}"), timeout=5
            )
            assert status == 200, "entry detail 被挂起的 AI/TTS 阻断"
            assert b"contentText" in body
            status, _ = await asyncio.wait_for(
                _asgi_request(
                    app, "PATCH", f"/api/v1/entries/{REF}/state", {"read": True}
                ),
                timeout=5,
            )
            assert status == 204, "read/star 写被挂起的 AI/TTS 阻断"
            status, _ = await asyncio.wait_for(
                _asgi_request(app, "GET", "/api/v1/search", query="q=test"), timeout=5
            )
            assert status == 200, "search 被挂起的 AI/TTS 阻断"
            elapsed = time.monotonic() - started
            assert elapsed < 10, f"四个核心阅读请求共耗时 {elapsed:.1f}s（存在耦合阻塞）"

            # 5. 收尾：取消挂起的能力请求（孤悬任务清理），阅读面依旧健康
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            status, _ = await asyncio.wait_for(
                _asgi_request(app, "GET", "/api/v1/entries"), timeout=5
            )
            assert status == 200, "取消后阅读面被未处理拒绝带坏"


def test_hung_ai_translation_tts_do_not_block_core_reading(monkeypatch):
    """三能力同时挂在上游 → 列表/详情/读星/搜索照常；取消后依旧健康。"""
    asyncio.run(_scenario(monkeypatch))
