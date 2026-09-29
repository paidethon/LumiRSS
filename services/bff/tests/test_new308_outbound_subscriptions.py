"""NEW-308 外发 Webhook 事件订阅 — 事件词表/验证门/暂停撤销/范围展示
/秘密只出现一次 + A/B 隔离。（本文件零网络：投递在 309 文件用假传输）"""

import asyncio

from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册


def _run(coroutine):
    return asyncio.run(coroutine)


def _create(client, *, event="entry.starred", url="https://hook.example.com/l"):
    response = client.post(
        "/api/v1/webhooks/out-subscriptions",
        json={"eventType": event, "targetUrl": url},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _activate(client, draft):
    response = client.post(
        f"/api/v1/webhooks/out-subscriptions/{draft['id']}/verify",
        json={"token": draft["verifyToken"]},
    )
    assert response.status_code == 200, response.text
    return draft["id"]


def test_new308_create_shows_secret_and_token_once(client):
    body = _create(client, event="library.item_created", url="https://hook.example.com/a")
    assert body["state"] == "pending"
    assert body["secret"] and body["verifyToken"]

    listed = client.get("/api/v1/webhooks/out-subscriptions").json()
    row = [r for r in listed["items"] if r["id"] == body["id"]][0]
    assert "secret" not in row and "verifyToken" not in row
    assert row["targetHost"] == "hook.example.com"
    assert "entry.starred" in listed["eventTypes"]

    same = client.post(
        "/api/v1/webhooks/out-subscriptions",
        json={
            "eventType": "library.item_created",
            "targetUrl": "https://hook.example.com/a",
        },
    )
    assert same.status_code == 422  # 同事件+同地址唯一
    insecure = client.post(
        "/api/v1/webhooks/out-subscriptions",
        json={
            "eventType": "library.item_created",
            "targetUrl": "http://evil.example/x",
        },
    )
    assert insecure.status_code == 422  # 仅 https 基线
    unknown = client.post(
        "/api/v1/webhooks/out-subscriptions",
        json={"eventType": "everything.*", "targetUrl": "https://h.example/x"},
    )
    assert unknown.status_code == 422  # 词表收窄


def test_new308_verify_gate_and_lifecycle(client):
    draft = _create(client, url="https://hook.example.com/l1")
    wrong = client.post(
        f"/api/v1/webhooks/out-subscriptions/{draft['id']}/verify",
        json={"token": "wrong"},
    )
    assert wrong.status_code == 403
    assert _activate(client, draft) == draft["id"]
    again = client.post(
        f"/api/v1/webhooks/out-subscriptions/{draft['id']}/verify",
        json={"token": draft["verifyToken"]},
    )
    assert again.status_code == 403  # 验证门单次有效

    paused = client.post(f"/api/v1/webhooks/out-subscriptions/{draft['id']}/pause")
    assert paused.status_code == 200 and paused.json()["state"] == "paused"
    resumed = client.post(f"/api/v1/webhooks/out-subscriptions/{draft['id']}/resume")
    assert resumed.status_code == 200 and resumed.json()["state"] == "active"

    deleted = client.delete(f"/api/v1/webhooks/out-subscriptions/{draft['id']}")
    assert deleted.status_code == 204
    listed = client.get("/api/v1/webhooks/out-subscriptions").json()["items"]
    row = [x for x in listed if x["id"] == draft["id"]][0]
    assert row["state"] == "revoked"  # 终态保留（回执仍可查）
    assert (
        client.post(f"/api/v1/webhooks/out-subscriptions/{draft['id']}/pause").status_code
        == 409
    )


def test_new308_cross_user_scope(ab_env):  # noqa: F811 — pytest 夹具注册
    """A 的订阅不在 B 的清单；B 不能暂停/验证/撤销 A 的订阅。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    b = env["b"]
    created = client.post(
        "/api/v1/webhooks/out-subscriptions",
        headers=a,
        json={
            "eventType": "entry.starred",
            "targetUrl": "https://hook.example.com/ab",
        },
    )
    assert created.status_code == 201, created.text
    target_id = str(created.json()["id"])
    token = created.json()["verifyToken"]

    wrong = client.post(
        f"/api/v1/webhooks/out-subscriptions/{target_id}/pause", headers=b, json={}
    )
    assert wrong.status_code in (404, 409)
    verify_as_b = client.post(
        f"/api/v1/webhooks/out-subscriptions/{target_id}/verify",
        headers=b,
        json={"token": token},
    )
    assert verify_as_b.status_code in (403, 404)
    revoke_as_b = client.delete(
        f"/api/v1/webhooks/out-subscriptions/{target_id}", headers=b
    )
    assert revoke_as_b.status_code in (404, 409)

    listed = client.get(
        "/api/v1/webhooks/out-subscriptions", headers=b
    ).json()["items"]
    assert all(row["id"] != created.json()["id"] for row in listed)
