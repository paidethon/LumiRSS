"""F008 摘要时区 + nextSendAt —— 设置响应携带下次发送时间；非法时区 422。

- GET /api/v1/digest/settings 在 enabled 时返回 nextSendAt（配置时区墙钟）；
- PUT timezone 非法 IANA 名称 → 422 invalid_timezone（不静默回退）；
- 跨日计算边界（今天已过 → 明天）引用既有 digest_timezone 用例。
"""

import asyncio

import pytest


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture()
def digest_env(client):
    return client


def test_f008_settings_next_send_at_and_timezone_roundtrip(digest_env):
    client = digest_env
    # 启用 + 合法时区
    put = client.put(
        "/api/v1/digest/settings",
        json={"enabled": True, "hour": 9, "timezone": "Asia/Shanghai"},
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["timezone"] == "Asia/Shanghai"
    assert body["nextSendAt"] is not None
    assert "T09:00:00" in body["nextSendAt"], "按配置时区墙钟（09:00）给出下次发送"

    # 关闭 → nextSendAt 清空
    off = client.put("/api/v1/digest/settings", json={"enabled": False}).json()
    assert off["nextSendAt"] is None

    # GET 一致
    got = client.get("/api/v1/digest/settings").json()
    assert got["timezone"] == "Asia/Shanghai"
    assert got["nextSendAt"] is None  # enabled=False


def test_f008_invalid_timezone_is_422_invalid_timezone(digest_env):
    client = digest_env
    bad = client.put(
        "/api/v1/digest/settings",
        json={"timezone": "Mars/Olympus_Mons"},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["type"] == "invalid_timezone"
    # 空串 = 服务器本地（合法）
    ok = client.put("/api/v1/digest/settings", json={"timezone": ""})
    assert ok.status_code == 200


def test_f008_cross_day_boundary_uses_next_send_at(client):
    """今天的小时已过 → 明天（既有 next_send_at 语义，此处经设置端点透出）。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    put = client.put(
        "/api/v1/digest/settings",
        json={"enabled": True, "hour": 3, "timezone": "Asia/Shanghai"},
    )
    body = put.json()
    assert body["nextSendAt"] is not None
    parsed = datetime.fromisoformat(body["nextSendAt"])
    assert parsed.tzinfo is not None
    now_shanghai = datetime.now(ZoneInfo("Asia/Shanghai"))
    if now_shanghai.hour >= 3:
        assert parsed.date() > now_shanghai.date(), "已过 03:00 → 明天"
    else:
        assert parsed.date() >= now_shanghai.date()
