"""FIX-365 — 客户端断开后服务端生成器不释放连接（取消传播）。

判定：BASELINE_OK（设计意图 + 机制核验）。BFF 唯一的流式响应是
agent SSE（GET /api/v1/agent/threads/{id}/events，全仓唯一
StreamingResponse）。其行为分两层，两层都必须成立：

1. 订阅资源必须随断开释放：Starlette StreamingResponse 收到
   http.disconnect 即取消流任务，CancelledError 落进生成器挂起点，
   ``finally: loop.unsubscribe(thread_id, queue)`` 执行——断开客户端
   的订阅队列必须从 loop._subscribers 移除，回合后续 publish 不再
   向死队列投递；
2. 回合本身不随断开中止——这是 agent 的明示产品语义（模块
   docstring「disconnect-friendly」+ SSE 路由 docstring「Disconnects
   never abort the server-side run — clients reconnect with `after`」
   + 专门的 POST /cancel 终止端点），不属于「泄漏的生成器」：回合
   状态全部持久化，重连重放存储行。

本文件用 raw-ASGI 驱动真实 app（TestClient/httpx ASGITransport 不会
向 app 发 http.disconnect，无法仿真断开）：断开后 app 调用必须在
远小于 120s idle 超时的时间内返回（等待即证明取消未传播），且
订阅集为空。无真实秘密。
"""

import asyncio
import time

from lumirss.agent_store import AgentStore
from lumirss.main import app


def run(coroutine):
    return asyncio.run(coroutine)


def _scope(method: str, path: str) -> dict:
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
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 123),
        "server": ("testserver", 80),
        "extensions": {},
    }


async def _asgi_request(
    app,
    method: str,
    path: str,
    *,
    disconnect_event: asyncio.Event | None = None,
    on_first_body_chunk=None,
):
    """Raw-ASGI 请求：首个 body 分片回调；后续 receive 在
    disconnect_event 置位后返回 http.disconnect（真实客户端断开）。"""
    scope = _scope(method, path)
    request_sent = False

    async def receive():
        nonlocal request_sent
        if request_sent:
            if disconnect_event is not None:
                await disconnect_event.wait()
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": b"", "more_body": False}

    status: dict[str, int] = {}
    chunks: list[bytes] = []

    async def send(message):
        if message["type"] == "http.response.start":
            status["code"] = message["status"]
        elif message["type"] == "http.response.body":
            body = message.get("body", b"")
            if body:
                chunks.append(body)
                if on_first_body_chunk is not None and len(chunks) == 1:
                    on_first_body_chunk.set()

    await app(scope, receive, send)
    return status.get("code"), b"".join(chunks)


async def _open_live_stream(thread_id: str):
    """打开 SSE 流并等到首个重放分片（生成器进入 live 等待）。"""
    first_chunk = asyncio.Event()
    disconnect = asyncio.Event()
    task = asyncio.ensure_future(
        _asgi_request(
            app,
            "GET",
            f"/api/v1/agent/threads/{thread_id}/events",
            disconnect_event=disconnect,
            on_first_body_chunk=first_chunk,
        )
    )
    await asyncio.wait_for(first_chunk.wait(), timeout=10)
    return task, disconnect


async def _drive_sse_disconnect(store: AgentStore):
    thread = await store.create_thread("FIX-365")
    thread_id = str(thread["id"])
    await store.append_message(
        thread_id, role="user", content={"text": "断开测试"}
    )
    # 运行标记让生成器进入 live 等待分支（而非立即 done 返回）。
    await store.mark_run_processing(thread_id)

    task, disconnect = await _open_live_stream(thread_id)

    # 生成器此刻挂在 queue.get 的 wait_for 上——模拟客户端断开。
    disconnect.set()
    started = time.monotonic()
    status, body = await asyncio.wait_for(task, timeout=10)
    elapsed = time.monotonic() - started

    assert status == 200
    assert b"event: message" in body
    # 若取消未传播，这里要等 120s idle 超时——10s wait_for 会先炸。
    assert elapsed < 5
    loop = app.state.agent_loop
    assert loop is not None
    # finally: unsubscribe 必须已执行——该线程无残留订阅队列。
    assert not loop._subscribers.get(thread_id)

    # 断开后回合仍按明示语义在后台存活（可 reconnect 重放）——
    # 运行标记未被 SSE 断开清除（终止要显式走 POST /cancel）。
    assert await store.is_running(thread_id) is True


def test_client_disconnect_releases_sse_subscription_and_returns_promptly():
    """断开 → 生成器被取消（finally 释放订阅队列）且调用即刻返回。"""

    async def scenario():
        async with app.router.lifespan_context(app):
            from lumirss.accounts_store import AccountsStore
            from lumirss.user_scope import user_context

            owners = await AccountsStore(app.state.control_db).list_users(limit=10)
            owner_id = next(
                str(row["id"]) for row in owners if row["role"] == "owner"
            )
            with user_context(owner_id):
                await _drive_sse_disconnect(AgentStore(app.state.db))

    run(scenario())


def test_publish_after_disconnect_does_not_touch_released_queue():
    """发布面回归：订阅释放后 publish 不再触达死队列（slow-subscriber
    丢弃路径只作用于在册队列）。"""
    import contextlib

    async def scenario():
        async with app.router.lifespan_context(app):
            from lumirss.accounts_store import AccountsStore
            from lumirss.user_scope import user_context

            owners = await AccountsStore(app.state.control_db).list_users(limit=10)
            owner_id = next(
                str(row["id"]) for row in owners if row["role"] == "owner"
            )
            with user_context(owner_id):
                store = AgentStore(app.state.db)
                thread = await store.create_thread("FIX-365b")
                thread_id = str(thread["id"])
                await store.mark_run_processing(thread_id)

                task, disconnect = await _open_live_stream(thread_id)
                disconnect.set()
                await asyncio.wait_for(task, timeout=10)

                loop = app.state.agent_loop
                assert not loop._subscribers.get(thread_id)
                # 死队列已不在册：publish 只遍历在册集合（list 快照），
                # 不得抛错、不得复活队列。
                with contextlib.suppress(asyncio.QueueFull):
                    loop.publish(
                        thread_id, {"type": "turn_done", "status": "completed"}
                    )
                assert not loop._subscribers.get(thread_id)

    run(scenario())
