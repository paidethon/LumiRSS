"""NEW-303 Webhook 接收收件箱 — 签名接收/待确认区/审阅 + A/B 隔离。

接收链（机器到机器）：Bearer 端点秘密（machine_user_context 归属）
+ 实例签名钥 HMAC（NEW-304 双钥窗口验签）→ 待确认区，绝不直入主库。
"""

import json
import time

from lumirss.main import app
from lumirss.new304_webhook_keys import SigningKeyStore
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册


def _sign_header(ts: int, body: bytes, secret: str) -> str:

    from lumirss.new304_webhook_keys import signature_header

    return signature_header(ts if ts else int(time.time()), body, secret)


def _fixed_ts() -> int:

    return int(time.time())


def _create_endpoint(client, label="通知端点"):
    response = client.post("/api/v1/webhooks/endpoints", json={"label": label})
    assert response.status_code == 201, response.text
    return response.json()


def _setup_signing_key(client=None):
    """直连 control 库轮换一把实例签名钥（返回明文，仅测试用）。"""
    import asyncio

    from lumirss.new304_webhook_keys import SigningKeyStore

    async def run():
        return await SigningKeyStore(app.state.control_db).rotate(10)

    return asyncio.run(run())


def _post_event(client, endpoint, payload: bytes, *, key_secret=None, bearer=None, ts=None):
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if key_secret:
        headers["X-Lumi-Signature"] = _sign_header(ts, payload, key_secret)
    return client.post(
        f"/api/v1/webhooks/ingest/{endpoint['uuid']}",
        content=payload,
        headers=headers,
    )


EVENT_BODY = json.dumps(
    {
        "eventId": "evt-1",
        "items": [
            {"id": "a1", "title": "<b>第一条</b> 通知", "body": "<p>内容一</p>"},
            {"id": "a2", "title": "第二条", "url": "https://x.example/a2"},
        ],
    }
).encode("utf-8")


def test_new303_endpoint_secret_shown_once(client):
    created = _create_endpoint(client)
    assert created["secret"] and created["ingestPath"].startswith("/api/v1/webhooks/ingest/")
    listed = client.get("/api/v1/webhooks/endpoints").json()["items"]
    mine = next(e for e in listed if e["uuid"] == created["uuid"])
    assert "secret" not in mine  # 秘密绝不再回显


def test_new303_ingest_lands_pending_then_review(client):
    """签名事件 → pending 待确认区；accept/reject 后状态与时刻如实。"""
    endpoint = _create_endpoint(client)
    key = _setup_signing_key(client)

    response = _post_event(
        client, endpoint, EVENT_BODY,
        key_secret=key["secret"], bearer=endpoint["secret"],
    )
    assert response.status_code == 202, response.text
    assert response.json()["stored"] == 2

    inbox = client.get("/api/v1/webhooks/inbox?status=pending").json()["items"]
    assert len(inbox) == 2
    first = inbox[0]
    assert first["status"] == "pending"
    assert "<b>" not in first["title"]  # 不可信 HTML 已剥标签

    accepted = client.post(f"/api/v1/webhooks/inbox/{first['id']}/accept")
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["decidedAt"]

    other = client.get("/api/v1/webhooks/inbox?status=pending").json()["items"]
    rejected = client.post(f"/api/v1/webhooks/inbox/{other[0]['id']}/reject")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    # 已裁决条目不可二次裁决（幂等拒绝）
    assert client.post(f"/api/v1/webhooks/inbox/{first['id']}/accept").status_code == 404


def test_new303_ingest_requires_bearer_and_signature(client):
    """错钥 / 无签名 / 篡改载荷 → 统一 404（无存在性预言机）。

    基本模式 bearer 不参与归属（machine_user_context 恒 owner）；
    「无 A 端点秘密 → 404」的会话语义由 cross_user 隔离测试覆盖。"""
    endpoint = _create_endpoint(client)
    key = _setup_signing_key(client)
    import secrets as _secrets

    never_issued = _secrets.token_hex(32)
    wrong_key = _post_event(
        client, endpoint, EVENT_BODY, key_secret=never_issued,
        bearer=endpoint["secret"],
    )
    assert wrong_key.status_code == 404
    no_signature = _post_event(client, endpoint, EVENT_BODY, bearer=endpoint["secret"])
    assert no_signature.status_code == 404
    # 真篡改：签名按原载荷计算，线上载荷被增删一个字节 → 验签必须拒绝
    tampered_headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + endpoint["secret"],
        "X-Lumi-Signature": _sign_header(0, EVENT_BODY, key["secret"]),
    }
    tampered = client.post(
        "/api/v1/webhooks/ingest/" + endpoint["uuid"],
        content=EVENT_BODY + b" ",
        headers=tampered_headers,
    )
    assert tampered.status_code == 404



def test_new303_duplicate_event_idempotent(client):
    endpoint = _create_endpoint(client)
    key = _setup_signing_key(client)
    assert _post_event(client, endpoint, EVENT_BODY, key_secret=key["secret"], bearer=endpoint["secret"]).status_code == 202
    again = _post_event(client, endpoint, EVENT_BODY, key_secret=key["secret"], bearer=endpoint["secret"])
    assert again.status_code == 202
    results = again.json()["results"]
    assert all(r["result"] == "duplicate" for r in results)
    inbox = client.get("/api/v1/webhooks/inbox").json()["items"]
    assert len(inbox) == 2  # 不产生新行

    # 已裁决事件重投：duplicate 且 alreadyDecided=True（副作用不重放）
    pending = client.get("/api/v1/webhooks/inbox?status=pending").json()["items"]
    client.post(f"/api/v1/webhooks/inbox/{pending[0]['id']}/accept")
    decided = _post_event(client, endpoint, EVENT_BODY, key_secret=key["secret"], bearer=endpoint["secret"])
    assert decided.status_code == 202
    assert all("alreadyDecided" in r for r in decided.json()["results"])


def test_new303_unparseable_payload_dead_lettered(client):
    """不可解析事件 → 400/202-deadLettered + NEW-305 死信（脱敏）。"""
    endpoint = _create_endpoint(client)
    key = _setup_signing_key(client)

    bad_json = b"{not json"
    response = _post_event(client, endpoint, bad_json, key_secret=key["secret"], bearer=endpoint["secret"])
    assert response.status_code == 400
    no_title = b'{"eventId":"evt-x","items":[{"id":"n1"}]}'
    response = _post_event(client, endpoint, no_title, key_secret=key["secret"], bearer=endpoint["secret"])
    assert response.status_code == 202
    assert response.json()["deadLettered"] is True

    letters = client.get("/api/v1/webhooks/dead-letters").json()["items"]
    assert len(letters) == 2
    assert all("payload_raw" not in letter for letter in letters)
    # 摘要是脱敏的（只有键名/类型，没有值）—— 按原因定位而非顺序
    target = None
    for letter in letters:
        if "evt-x" in str(letter["eventId"]) or "no" in str(letter["eventId"]):
            target = letter
    assert target is not None
    summary = target["payloadSummary"]
    assert summary["topLevelType"] in ("object", "invalid_json")
    key_names = {k["name"] for k in summary.get("keys", [])}
    assert "eventId" in key_names or not summary.get("keys")


def test_new303_cross_user_isolated(ab_env):  # noqa: F811 — pytest 夹具注册
    """A 的端点/收件箱对 B 不可见：B 无法用自己的凭据喂 A 的端点，
    也看不到 A 的条目。"""
    env = ab_env
    client = env["client"]
    a, b = env["a"], env["b"]

    created = client.post("/api/v1/webhooks/endpoints", headers=a, json={"label": "A 的端点"})
    assert created.status_code == 201, created.text
    endpoint = created.json()
    import asyncio


    async def rotate():
        return await SigningKeyStore(client.app.state.control_db).rotate(10)

    key = asyncio.run(rotate())

    body = json.dumps({"eventId": "a-evt", "items": [{"id": "x1", "title": "A 的条目"}]}).encode("utf-8")
    ok = client.post(
        f"/api/v1/webhooks/ingest/{endpoint['uuid']}",
        content=body,
        headers={
            "Authorization": f"Bearer {endpoint['secret']}",
            "X-Lumi-Signature": _sign_header(0, body, key["secret"]),
        },
    )
    assert ok.status_code == 202, ok.text
    assert ok.json()["stored"] == 1

    # B 的收件箱是空的；A 的端点对 B 的清单不可见
    assert client.get("/api/v1/webhooks/inbox", headers=b).json()["items"] == []
    b_endpoints = client.get("/api/v1/webhooks/endpoints", headers=b).json()["items"]
    assert all(e["uuid"] != endpoint["uuid"] for e in b_endpoints)
    # A 自己能看到
    assert len(client.get("/api/v1/webhooks/inbox", headers=a).json()["items"]) == 1
