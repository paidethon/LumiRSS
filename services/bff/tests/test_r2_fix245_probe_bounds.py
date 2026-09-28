"""FIX-245 — 单个坏来源不得占满刷新队列（每源并发与全局配额协调）。

F050 批量检查台就是本仓库的刷新探测队列。基线排查结论（BASELINE 验证，
本文件钉住既有边界）：

- 全局并发配额：``asyncio.Semaphore(4)`` —— 任意时刻至多 4 个在飞探测；
- 每源时限：``HealthCheckRequest.timeoutS``（1..10s）逐请求传入
  ``_probe_feed_url`` 的 HEAD/GET（httpx 客户端层强制），挂死源最坏
  占住一个槽位 ≤timeoutS 后按 timeout 归类，绝不永久占位；
- 批量上限：refs ≤ 50（payload 模型拒绝），重复 ref 去重。

行为测试：一个挂住的源占住一个槽位时，其余健康源照常完成（完成耗时
符合并发上界下的预期，而非串行累加）。
"""

import asyncio
import time
from types import SimpleNamespace

from lumirss.main import app
from lumirss.subscriptionref import encode_subscription_ref

URLS = [f"https://source-{i}.example.com/feed" for i in range(6)]


def _install_control():
    subs = [
        SimpleNamespace(
            stream_id=f"feed/{i + 1}",
            subscription_ref=encode_subscription_ref(f"feed/{i + 1}"),
            title=f"源{i}",
            feed_url=url,
            category_id=None,
            category_label=None,
        )
        for i, url in enumerate(URLS)
    ]

    async def _list():
        return list(subs)

    app.state.freshrss_control_adapter = SimpleNamespace(list_subscriptions=_list)
    return [sub.subscription_ref for sub in subs]


def test_hanging_source_does_not_starve_healthy_ones(client):
    """源 0 挂住 0.6s（真实路径里等价于“被 timeoutS 收走前的占位”），
    其余 5 个健康源各需 0.3s：并发 ≤4 配额下全部完成，总耗时符合并发
    预期（~0.6s）而非串行累加（~2.1s）。"""
    refs = _install_control()
    state = {"in_flight": 0, "max_in_flight": 0}

    async def fake_probe(feed_url, timeout_s):
        _ = timeout_s
        state["in_flight"] += 1
        state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
        try:
            if feed_url == URLS[0]:
                await asyncio.sleep(0.6)  # “挂住”的坏源
            await asyncio.sleep(0.3)  # 健康源的真实探测耗时
            return {"status": "ok", "httpStatus": 200}
        finally:
            state["in_flight"] -= 1

    app.state.health_probe = fake_probe
    started = time.monotonic()
    response = client.post(
        "/api/v1/subscriptions/health-check",
        json={"refs": refs, "timeoutS": 5},
    )
    elapsed = time.monotonic() - started

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 6, "挂住源不吞掉任何健康源的结果"
    assert all(item["status"] == "ok" for item in items)
    assert state["max_in_flight"] <= 4, "全局并发配额 ≤4"
    assert state["max_in_flight"] >= 2, "探测确实是并发的"
    assert elapsed < 1.5, (
        f"健康源不得排队等坏源（并发 ~0.6s，串行 ~2.1s）：{elapsed:.2f}s"
    )


def test_probe_batch_and_timeout_bounds_are_enforced(client):
    """结构性边界：refs ≤50、timeoutS ∈ [1,10]（每源时限的输入域）。"""
    _install_control()
    app.state.health_probe = None
    too_many = client.post(
        "/api/v1/subscriptions/health-check",
        json={"refs": [encode_subscription_ref(f"feed/{i + 1}") for i in range(51)]},
    )
    assert too_many.status_code == 422
    short_timeout = client.post(
        "/api/v1/subscriptions/health-check",
        json={"refs": [encode_subscription_ref("feed/1")], "timeoutS": 0.5},
    )
    assert short_timeout.status_code == 422
    long_timeout = client.post(
        "/api/v1/subscriptions/health-check",
        json={"refs": [encode_subscription_ref("feed/1")], "timeoutS": 11},
    )
    assert long_timeout.status_code == 422
