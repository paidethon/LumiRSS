"""NEW-304 Webhook 密钥轮换窗口 — 双钥窗口/切换结果/秘密不回显 + 权限。"""

import asyncio
import time

import pytest

from lumirss.new304_webhook_keys import (
    KeyRotationInvalid,
    SigningKeyStore,
    clean_window_minutes,
    signature_header,
    verify_webhook_signature,
)
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册


def _fixed_ts() -> int:

    return int(time.time())


def _run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture()
def key_db(tmp_path):
    from lumirss.storage import Database

    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    return db


def _body(text: str = "事件载荷") -> bytes:
    return text.encode("utf-8")


def test_new304_rotate_shows_secret_once_and_never_in_snapshot(key_db):
    store = SigningKeyStore(key_db)
    rotated = _run(store.rotate(10))
    assert rotated["secret"] and rotated["keyId"].startswith("wk_")
    assert rotated["previousKeyId"] is None  # 第一把钥
    snapshot = _run(store.snapshot())
    assert rotated["secret"] not in str(snapshot)  # 秘密绝不进报告
    assert snapshot["keys"][0]["state"] == "active"

    second = _run(store.rotate(15))
    assert second["previousKeyId"] == rotated["keyId"]
    snapshot = _run(store.snapshot())
    assert second["secret"] not in str(snapshot)
    states = {k["keyId"]: k["state"] for k in snapshot["keys"]}
    assert states[rotated["keyId"]] == "retiring"  # 双钥窗口
    assert states[second["keyId"]] == "active"


def test_new304_dual_window_verification(key_db):
    """窗口内旧钥仍可验证并计数；窗口过后只认新钥；篡改/过期拒绝。"""
    store = SigningKeyStore(key_db)
    first = _run(store.rotate(10))
    body = _body()
    header = signature_header(
        _fixed_ts(), body, first["secret"]
    )
    key_id = _run(verify_webhook_signature(key_db, body, header))
    assert key_id == first["keyId"]

    second = _run(store.rotate(10))
    # 新钥验证通过；旧钥仍在窗口内通过
    assert _run(verify_webhook_signature(key_db, body, signature_header(_fixed_ts(), body, second["secret"]))) == second["keyId"]
    assert _run(verify_webhook_signature(key_db, body, header)) == first["keyId"]

    # 篡改 → 拒绝；坏形状 → 拒绝；时间戳偏移过大 → 拒绝
    assert _run(verify_webhook_signature(key_db, body + b"x", header)) is None
    assert _run(verify_webhook_signature(key_db, body, "garbage")) is None
    stale = signature_header(
        1_000_000_000, body, second["secret"]
    )
    assert _run(verify_webhook_signature(key_db, body, stale)) is None

    # 窗口过期（把旧钥 window_ends_at 拨到过去）→ 只认新钥
    async def expire():
        await key_db.execute(
            "UPDATE webhook_signing_keys SET window_ends_at = '2020-01-01T00:00:00Z' "
            "WHERE key_id = ?",
            (first["keyId"],),
        )

    _run(expire())
    assert _run(verify_webhook_signature(key_db, body, header)) is None
    assert _run(
        verify_webhook_signature(
            key_db,
            body,
            signature_header(
                _fixed_ts(), body, second["secret"]
            ),
        )
    ) == second["keyId"]


def test_new304_switch_result_counters(key_db):
    """切换结果 = 每钥每日验证计数（新钥上升、旧钥趋零），无密钥材料。"""
    from lumirss.new304_webhook_keys import signature_header

    store = SigningKeyStore(key_db)
    first = _run(store.rotate(10))
    second = _run(store.rotate(10))
    body = _body()
    for _ in range(3):
        _run(verify_webhook_signature(key_db, body, signature_header(_fixed_ts(), body, second["secret"])))
    _run(verify_webhook_signature(key_db, body, signature_header(_fixed_ts(), body, first["secret"])))
    snapshot = _run(store.snapshot())
    counts = {k["keyId"]: (k["verifiedToday"], k["verifiedTotal"]) for k in snapshot["keys"]}
    assert counts[second["keyId"]] == (3, 3)
    assert counts[first["keyId"]][0] == 1
    assert "secret" not in str(snapshot).lower() or first["secret"] not in str(snapshot)


def test_new304_window_bounds():
    assert clean_window_minutes(None if False else 10) == 10
    with pytest.raises(KeyRotationInvalid):
        clean_window_minutes(0)
    with pytest.raises(KeyRotationInvalid):
        clean_window_minutes(61)


def test_new304_admin_surface_guarded(ab_env):  # noqa: F811 — pytest 夹具注册
    """member 一律 403；owner 需 step-up（op=webhook_key_rotation）；
    轮换响应明文只出现一次，GET 永不含密钥材料。"""
    env = ab_env
    client = env["client"]
    owner, bob = env["owner"], env["b"]

    denied = client.post("/api/v1/admin/webhook-keys/rotate", headers=bob, json={})
    assert denied.status_code == 403
    assert client.get("/api/v1/admin/webhook-keys", headers=bob).status_code == 403

    # 未提权的 owner → 403 step_up_required
    bare = client.post("/api/v1/admin/webhook-keys/rotate", headers=owner, json={})
    assert bare.status_code == 403
    assert bare.json()["error"]["type"] == "step_up_required"

    # owner 拿自己的 userId，铸造 step-up 令牌
    session = client.get("/api/v1/auth/session", headers=owner).json()
    owner_id = str(session["userId"])
    minted = client.post(
        "/api/v1/admin/step-up",
        headers=owner,
        json={
            "password": __import__("new2xx_ab").PASSWORD,
            "operation": "webhook_key_rotation",
            "targetUserId": owner_id,
        },
    )
    assert minted.status_code == 200, minted.text
    token = minted.json()["token"]

    rotated = client.post(
        "/api/v1/admin/webhook-keys/rotate",
        headers={**owner, "X-Lumi-Step-Up": token},
        json={"windowMinutes": 10},
    )
    assert rotated.status_code == 200, rotated.text
    secret = rotated.json()["secret"]
    assert secret

    snapshot = client.get("/api/v1/admin/webhook-keys", headers=owner)
    assert snapshot.status_code == 200
    assert secret not in snapshot.text  # 报告绝不含密钥材料
