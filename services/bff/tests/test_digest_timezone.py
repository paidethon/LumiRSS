"""Digest 时区与发送预览回归（pool #31）。

迁移 0024 起 ``hour`` 按配置的 IANA 时区解释（'' = 服务器本地，历史
语义）。用注入的固定时钟验证：时区切换改变发送窗口、跨日边界、只发送
一次语义；预览端点无副作用。
"""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from lumirss.mail_digest import (
    DigestScheduler,
    DigestStore,
    next_send_at,
    now_in_timezone,
)


def run(coroutine):
    return asyncio.run(coroutine)


def _store(client) -> DigestStore:
    """0067：直连调用（无请求上下文）需要显式用户作用域——routing
    secrets store 用 owner 的显式 uid 解析出普通 SecretsStore。"""
    from lumirss.main import app

    return DigestStore(
        app.state.db,
        app.state.secrets_store.store_for(app.state.owner_id),
    )


def test_timezone_roundtrip_and_invalid_fallback(client):
    store = _store(client)
    saved = run(store.save({"timezone": "Asia/Shanghai"}))
    assert saved["timezone"] == "Asia/Shanghai"
    # 非法 IANA 名保留现值（与 hour 的宽容校验同一风格）。
    saved = run(store.save({"timezone": "Mars/Olympus"}))
    assert saved["timezone"] == "Asia/Shanghai"
    # 空串显式回退服务器本地。
    saved = run(store.save({"timezone": ""}))
    assert saved["timezone"] == ""


def test_scheduler_uses_configured_timezone_not_server_local(client):
    """服务器在 CST 08:00、配置 UTC hour=8：本地 8 点不该发；UTC 8 点才发。"""
    store = _store(client)
    run(store.save({"enabled": True, "hour": 8, "timezone": "UTC"}))
    sent = []

    # 固定时钟：UTC 2000-01-01T08:00（= 服务器 CST 16:00，本地不是 8 点）。
    utc8 = datetime(2000, 1, 1, 8, 0, 30, tzinfo=ZoneInfo("UTC"))

    async def send(tag):
        # 真实 send 路径（deliver_digest → mark_sent）会记录发送时刻；
        # 测试用同一固定时钟写下 last_sent_at，与生产语义一致。
        await store._db.execute(
            "UPDATE digest_settings SET last_sent_at = ? WHERE id = 1",
            (utc8.isoformat(),),
        )
        sent.append(tag)

    scheduler = DigestScheduler(
        store._db, clock=lambda _tz: utc8
    )
    run(scheduler.maybe_send(lambda: send("utc")))
    assert sent == ["utc"], "UTC 8 点应发送（无视服务器本地时区）"

    # 只发送一次：last_sent 已是同一 UTC 边界 → 不再发。
    async def again():
        scheduler2 = DigestScheduler(store._db, clock=lambda _tz: utc8)
        await scheduler2.maybe_send(lambda: send("again"))

    run(again())
    assert sent == ["utc"]


def test_scheduler_honors_server_local_when_timezone_empty(client):
    """timezone='' 保持历史语义：按服务器本地时间解释 hour。"""
    store = _store(client)
    run(store.save({"enabled": True, "hour": 9, "timezone": ""}))
    sent = []

    async def send():
        sent.append("x")

    local_9 = datetime(2001, 3, 4, 9, 5, 0).astimezone()
    scheduler = DigestScheduler(store._db, clock=lambda _tz: local_9)
    run(scheduler.maybe_send(send))
    assert sent == ["x"]


def test_next_send_at_crosses_day_and_reports_tz_offset(client):
    now = datetime(2026, 9, 17, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    # hour=8 已过 → 明天 08:00。
    assert next_send_at(now, 8).startswith("2026-09-18T08:00:00+08:00")
    # hour=21 未到 → 今天 21:00。
    assert next_send_at(now, 21).startswith("2026-09-17T21:00:00+08:00")
    # 正点边界：now 恰为 08:00:00 → 已到点，排明天（避免重复发同一小时）。
    boundary = datetime(2026, 9, 17, 8, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert next_send_at(boundary, 8).startswith("2026-09-18T08:00:00+08:00")


def test_now_in_timezone_and_invalid_fallback(client):
    now = now_in_timezone("Asia/Shanghai")
    assert now.utcoffset().total_seconds() == 8 * 3600
    assert now_in_timezone("Mars/Olympus").tzinfo is not None  # 回退本地


def test_digest_preview_is_side_effect_free(client, monkeypatch):

    store = _store(client)
    run(store.save({"enabled": True, "hour": 8, "timezone": "UTC"}))
    response = client.get("/api/v1/digest/preview")
    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == "LumiRSS 文章摘要"
    assert body["itemCount"] == 0  # 无 bridge 条目：诚实为 0
    assert body["note"] is not None  # 空条目有解释
    assert body["nextSendAt"] is not None
    assert body["timezone"] == "UTC"
    # 无副作用：last_sent_at / last_error 均未被触碰。
    reloaded = run(store.load())
    assert reloaded["lastSentAt"] is None
    assert reloaded["lastError"] is None
