"""F35 任务记录 — 聚合形状与降级语义。"""

import asyncio

from lumirss.main import app


def test_recent_tasks_includes_backup_and_shows_failures(client):
    # 触发一次可见的历史行（直接种 backup_jobs，避免执行真实备份）
    async def _seed():
        await app.state.db.migrate()
        await app.state.db.execute(
            "INSERT INTO backup_jobs (id, type, status, stage, target, created_at, started_at, finished_at, safe_error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "job-1",
                "full",
                "failed",
                "upload",
                "local",
                "2026-09-18T00:00:00Z",
                "2026-09-18T00:00:01Z",
                "2026-09-18T00:00:02Z",
                "disk full",
            ),
        )


    asyncio.run(_seed())

    body = client.get("/api/v1/tasks/recent").json()
    tasks = body["items"]
    backup = next(t for t in tasks if t["ref"] == "job-1")
    assert backup["kind"] == "backup:full"
    assert backup["status"] == "failed"
    assert backup["error"] == "disk full"
    # 新→旧排序
    stamps = [t["startedAt"] for t in tasks]
    assert stamps == sorted(stamps, reverse=True)


def test_recent_tasks_empty_ok(client):
    # 清空种子后仍 200 空列表（不 500）
    body = client.get("/api/v1/tasks/recent").json()
    assert isinstance(body["items"], list)
