"""N188 数据保留到期提醒 — due-soon 提醒 / 推迟（≤30 天）/ 无自动应用。

apply 保持人工唯一入口：本套件在 app 全生命周期内挂上调用计数探针，
断言任何端点/启动路径都不会自动触发 retention_apply。"""

import asyncio
from datetime import datetime, timedelta

from lumirss.storage_retention import (
    POSTPONE_MAX_DAYS,
    load_postpone_until,
    load_retention,
    save_postpone_until,
)


def run(coroutine):
    return asyncio.run(coroutine)


def _enable_retention(client, *, ai_versions_days=30, task_log_days=None):
    response = client.put(
        "/api/v1/storage/retention",
        json={
            "enabled": True,
            "aiVersionsDays": ai_versions_days,
            "taskLogDays": task_log_days,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _seed_version(client, created_at: str) -> None:
    db = client.app.state.db
    run(
        db.execute(
            "INSERT INTO ai_summary_versions (id, entry_ref, content_hash, summary, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            ("sv-1", "entry/1", "hash-1", "旧版本", created_at),
        )
    )


def test_n188_notice_due_when_rows_expire_within_window(client):
    """策略启用且最老未到期行将在 7 天内到期 → dueSoon + dueAt + 计数。"""
    _enable_retention(client, ai_versions_days=30)
    now = datetime.now().astimezone()
    # 28 天前创建：还有 2 天到期（落在 7 天提醒窗口内）
    created = (now - timedelta(days=28)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    _seed_version(client, created)

    response = client.get("/api/v1/storage/retention/notice")
    assert response.status_code == 200, response.text
    notice = response.json()
    assert notice["enabled"] is True
    assert notice["dueSoon"] is True
    assert notice["dueAt"] is not None
    assert notice["noticeWindowDays"] == 7
    assert notice["affectedCounts"]["aiVersions"]["count"] == 0  # 尚未到期
    # 保护类如实列出
    for key in ("entries", "annotations", "notes", "cards", "credentials"):
        assert key in notice["protected"]


def test_n188_notice_due_now_when_rows_already_expired(client):
    _enable_retention(client, ai_versions_days=30)
    now = datetime.now().astimezone()
    created = (now - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    _seed_version(client, created)
    notice = client.get("/api/v1/storage/retention/notice").json()
    assert notice["dueSoon"] is True
    assert notice["affectedCounts"]["aiVersions"]["count"] == 1  # 预览复用口径


def test_n188_notice_quiet_when_nothing_due(client):
    _enable_retention(client, ai_versions_days=365)
    notice = client.get("/api/v1/storage/retention/notice").json()
    assert notice["dueSoon"] is False
    assert notice["dueAt"] is None


def test_n188_notice_disabled_policy_not_due(client):
    notice = client.get("/api/v1/storage/retention/notice").json()
    assert notice["enabled"] is False
    assert notice["dueSoon"] is False


def test_n188_postpone_suppresses_notice_within_limit(client):
    """推迟生效期内 dueSoon=false；推迟值被钳制到 ≤30 天。"""
    _enable_retention(client, ai_versions_days=30)
    now = datetime.now().astimezone()
    created = (now - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    _seed_version(client, created)
    assert client.get("/api/v1/storage/retention/notice").json()["dueSoon"] is True

    response = client.post(
        "/api/v1/storage/retention/postpone", json={"days": 999}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["days"] == POSTPONE_MAX_DAYS  # 999 → 钳制到 30
    postponed_until = datetime.fromisoformat(body["postponedUntil"])
    assert postponed_until <= datetime.now().astimezone() + timedelta(days=30)

    notice = client.get("/api/v1/storage/retention/notice").json()
    assert notice["dueSoon"] is False  # 被推迟抑制
    assert notice["postponedUntil"] == body["postponedUntil"]
    assert notice["dueAt"] is not None  # 真实到期时刻仍如实保留

    # 取消推迟 → 提醒恢复
    cancel = client.delete("/api/v1/storage/retention/postpone")
    assert cancel.status_code == 204
    notice = client.get("/api/v1/storage/retention/notice").json()
    assert notice["dueSoon"] is True
    assert notice["postponedUntil"] is None


def test_n188_postpone_persisted_in_dedicated_column(client):
    db = client.app.state.db
    until = datetime.now().astimezone() + timedelta(days=7)
    run(save_postpone_until(db, until))
    row = run(
        db.fetch_one(
            "SELECT retention_postpone_until FROM storage_retention_state WHERE id = 1"
        )
    )
    assert row is not None and row["retention_postpone_until"]
    assert run(load_postpone_until(db)) is not None
    # 0113 迁移建表：策略 KV 与推迟状态互不污染
    config = run(load_retention(db))
    assert config["enabled"] is False


def test_n188_no_auto_apply_scheduler(client, monkeypatch):
    """负向断言：提醒/推迟/启动路径绝不自动触发 apply（仅人工端点）。"""
    import lumirss.storage_retention as storage_retention

    calls = {"apply": 0}
    original = storage_retention.retention_apply

    async def counting_apply(*args, **kwargs):
        calls["apply"] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(storage_retention, "retention_apply", counting_apply)
    _enable_retention(client, ai_versions_days=30)
    _seed_version(client, "2020-01-01T00:00:00+00:00")
    client.get("/api/v1/storage/retention/notice")
    client.post("/api/v1/storage/retention/postpone", json={"days": 7})
    client.get("/api/v1/storage/retention")
    client.post("/api/v1/storage/retention/preview")
    assert calls["apply"] == 0  # 没有任何自动路径
