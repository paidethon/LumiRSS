"""NEW-309 Webhook 投递回执 — 脱敏响应/退避计划/同一幂等键手动重试
/到点计划处理 + A/B 隔离。（假传输，零真实网络）"""

import asyncio
import json

import lumirss.new308_outbound_subscriptions as outbound_module
import lumirss.routers.new309_deliveries as retry_router
from lumirss.main import app
from lumirss.new309_delivery_receipts import (
    MAX_ATTEMPTS,
    next_retry_at,
    sanitize_response_excerpt,
)
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册


def _run(coroutine):
    return asyncio.run(coroutine)


class FakeTarget:
    """可编程假目标：记录 (url, headers, body)，返回设定响应。"""

    def __init__(self, status=200, text='{"ok":true"'):
        self.status = 200 if status == 200 else status
        self.text = '{"ok":true}' if text is None else text
        self.calls = []

    async def __call__(self, url, headers, body):
        self.calls.append({"url": url, "headers": headers, "body": body})
        return self.status, "application/json; charset=utf-8", self.text


def _create_and_activate(client, url="https://hook.example.com/d"):
    created = client.post(
        "/api/v1/webhooks/out-subscriptions",
        json={"eventType": "entry.starred", "targetUrl": url},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    verified = client.post(
        f"/api/v1/webhooks/out-subscriptions/{body['id']}/verify",
        json={"token": body["verifyToken"]},
    )
    assert verified.status_code == 200, verified.text
    return body["id"]


def _dispatch(client, sender, *, data=None):
    original = outbound_module._http_sender
    outbound_module._http_sender = sender
    try:
        return client.post(
            "/api/v1/webhooks/out-subscriptions/dispatch",
            json={"eventType": "entry.starred", "data": data or {"note": "x"}},
        )
    finally:
        outbound_module._http_sender = original


def test_new309_sanitize_and_backoff_units():
    excerpt = sanitize_response_excerpt(
        "application/json; charset=utf-8", 'sound\b\x00' + "x" * 400
    )
    assert excerpt.startswith("[application/json]")
    assert "\x00" not in excerpt and "\b" not in excerpt
    assert len(excerpt) <= 320 and excerpt.endswith("…")
    assert sanitize_response_excerpt("image/png", None) == "[image/png] (无响应体)"
    first = next_retry_at(1, now="2026-09-29T00:00:00Z")
    assert first == "2026-09-29T00:01:00Z"  # 1 分钟退避
    final = next_retry_at(MAX_ATTEMPTS, now="2026-09-29T00:00:00Z")
    assert final == ""  # 计划耗尽：无下一次


def test_new309_receipts_sanitized_never_show_signature(client):
    """成功投递：回执只有状态码+媒体族+文本摘要；签名/请求头名绝不
    出现在回执任何字段。"""
    good = FakeTarget(status=200)
    subscription_id = _create_and_activate(client, "https://hook.example.com/r1")
    response = _dispatch(client, good)
    assert response.status_code == 200, response.text
    assert len(good.calls) == 1
    headers = good.calls[0]["headers"]
    assert headers["X-Lumi-Signature"].startswith("t=")
    delivery_key = headers["X-Lumi-Delivery"]

    listed = client.get(
        "/api/v1/webhooks/deliveries?subscriptionId=" + str(subscription_id)
    ).json()["items"]
    assert len(listed) == 1
    row = json.loads(json.dumps(listed[0]))
    assert row["status"] == "success" and row["attempt"] == 1
    assert row["responseStatus"] == 200
    assert row["responseExcerpt"].startswith("[application/json]")
    flat = json.dumps(row).lower()
    assert "signature" not in flat and "x-lumi" not in flat
    assert row["idempotencyKey"] == delivery_key


def test_new309_manual_retry_uses_same_idempotency_key(client):
    """失败 → 回执 failed + 重试计划；目标恢复后手动重试：**同一幂等
    键**、attempt+1、成功回执，且目标收到的 X-Lumi-Delivery 相同。"""
    failing = FakeTarget(status=500, text="boom")
    healthy = FakeTarget(status=200)
    subscription_id = _create_and_activate(client, "https://hook.example.com/r2")

    first = _dispatch(client, failing)
    assert first.status_code == 200 and first.json()["results"][0]["ok"] is False
    rows = client.get(
        "/api/v1/webhooks/deliveries?subscriptionId=" + str(subscription_id)
    ).json()["items"]
    assert len(rows) == 1
    original = rows[0]
    assert original["status"] == "failed"
    assert original["nextRetryAt"]
    family_key = original["idempotencyKey"]

    previous_sender = retry_router._INJECTABLE_SENDER
    retry_router.set_injectable_sender(healthy)
    try:
        retry = client.post(
            "/api/v1/webhooks/deliveries/" + str(original["id"]) + "/retry",
            json={},
        )
    finally:
        retry_router.set_injectable_sender(previous_sender)
    assert retry.status_code == 200, retry.text
    retried = retry.json()
    assert retried["attempt"] == 2
    assert retried["idempotencyKey"] == family_key
    assert retried["status"] == "success"
    assert len(healthy.calls) == 1
    assert healthy.calls[0]["headers"]["X-Lumi-Delivery"] == family_key

    rows_after = client.get(
        "/api/v1/webhooks/deliveries?subscriptionId=" + str(subscription_id)
    ).json()["items"]
    assert len(rows_after) == 2
    assert len({row["idempotencyKey"] for row in rows_after}) == 1


def test_new309_process_due_and_exhausted_cap(client):
    """到点计划处理只重试到点的失败投递；计划上限（5 次）后拒绝自动
    重试（409），用户可另建订阅。"""
    failing = FakeTarget(status=503, text="later")
    subscription_id = _create_and_activate(client, "https://hook.example.com/p1")
    _dispatch(client, failing)
    rows = client.get("/api/v1/webhooks/deliveries").json()["items"]
    assert rows[0]["status"] == "failed"

    healthy = FakeTarget(status=200)

    async def _backdate():
        await app.state.db.migrate()
        await app.state.db.execute(
            "UPDATE webhook_deliveries SET next_retry_at = '2000-01-01T00:00:00Z' "
            "WHERE subscription_id = ?",
            (subscription_id,),
        )

    _run(_backdate())
    previous = retry_router._INJECTABLE_SENDER
    retry_router.set_injectable_sender(healthy)
    try:
        due = client.post("/api/v1/webhooks/deliveries/process-due", json={})
        assert due.status_code == 200, due.text
        assert due.json()["processed"] >= 1
    finally:
        retry_router.set_injectable_sender(previous)
    assert healthy.calls and healthy.calls[0]["headers"]["X-Lumi-Event"] == "entry.starred"

    rows = client.get(
        "/api/v1/webhooks/deliveries?subscriptionId=" + str(subscription_id)
    ).json()["items"]
    newest = rows[0]
    assert newest["attempt"] == 2  # process-due 已产生第二次尝试

    async def _flood_that(row_id):
        await app.state.db.migrate()
        await app.state.db.execute(
            "UPDATE webhook_deliveries SET attempt = ?, status = 'exhausted', "
            "next_retry_at = NULL WHERE id = ?",
            (MAX_ATTEMPTS, row_id),
        )

    _run(_flood_that(newest["id"]))
    denied = client.post(
        "/api/v1/webhooks/deliveries/" + str(newest["id"]) + "/retry", json={}
    )
    assert denied.status_code == 409


def test_new309_cross_user_receipts_invisible(ab_env):  # noqa: F811 — pytest 夹具注册
    """A 的投递回执对 B 不可见；B 不能重试 A 的投递。"""
    env = ab_env
    client = env["client"]
    a, b = env["a"], env["b"]
    created = client.post(
        "/api/v1/web/hooks/OUT".replace("/web/hooks/OUT", "/webhooks/out-subscriptions"),
        headers=a,
        json={
            "eventType": "reading.progress_changed",
            "targetUrl": "https://hook.example.com/iso",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert (
        client.post(
            f"/api/v1/webhooks/out-subscriptions/{body['id']}/verify",
            headers=a,
            json={"token": body["verifyToken"]},
        ).status_code
        == 200
    )
    b_rows = client.get("/api/v1/webhooks/deliveries", headers=b).json()["items"]
    assert b_rows == []
    import lumirss.new308_outbound_subscriptions as out_mod

    ok_target = FakeTarget(status=200)
    saved = out_mod._http_sender
    out_mod._http_sender = ok_target
    try:
        dispatched = client.post(
            "/api/v1/webhooks/out-subscriptions/dispatch",
            headers=a,
            json={"eventType": "reading.progress_changed", "data": {"x": 1}},
        )
    finally:
        out_mod._http_sender = saved
    assert dispatched.status_code == 200, dispatched.text
    assert dispatched.json()["results"] and dispatched.json()["results"][0]["ok"] is True

    a_rows = client.get("/api/v1/webhooks/deliveries", headers=a).json()["items"]
    assert len(a_rows) == 1
    still_none_for_b = client.get(
        "/api/v1/webhooks/deliveries", headers=b
    ).json()["items"]
    assert still_none_for_b == []
    foreign_retry = client.post(
        "/api/v1/webhooks/deliveries/" + str(a_rows[0]["id"]) + "/retry",
        headers=b,
        json={},
    )
    assert foreign_retry.status_code == 404
