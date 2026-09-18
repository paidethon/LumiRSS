"""F35 用户任务记录 —— 聚合本应用后台任务的最近结果（只读）。

- 备份/安全/恢复任务（backup_jobs 0018 账本）；
- GPT 日报最近发布（gpt_digest_issues）；
- 邮件摘要最近发送/错误（digest_settings）。
明确排除：FreshRSS 内部 cron 的原始抓取（FreshRSS 域）；不暴露
PID/shell；limit 有界。取消端点刻意不提供——这些任务目前都不是可安全
中断的长任务（备份已有互斥，日报生成分钟级）。
"""

from typing import Any

from lumirss.storage import Database


class TaskRecordStore:
    """聚合只读视图（各域已有 store；本类不做任何写入）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def recent_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        await self._db.migrate()

        try:
            rows = await self._db.fetch_all(
                "SELECT id, type, status, created_at, started_at, finished_at, safe_error FROM backup_jobs ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            )
            for row in rows:
                tasks.append(
                    {
                        "kind": f"backup:{row['type']}",
                        "status": str(row["status"]),
                        "startedAt": str(row["started_at"] or row["created_at"] or ""),
                        "finishedAt": row["finished_at"],
                        "error": row["safe_error"],
                        "ref": str(row["id"]),
                    }
                )
        except Exception:  # noqa: BLE001 — 表缺失时诚实降级
            tasks = tasks

        try:
            rows = await self._db.fetch_all(
                "SELECT c.id AS config_id, c.name AS config_name, i.issue_key, i.published_at FROM gpt_digest_configs c JOIN gpt_digest_issues i ON i.config_id = c.id WHERE i.status = 'published' ORDER BY i.id DESC LIMIT ?",
                (limit,),
            )
            for row in rows:
                stamp = str(row["published_at"] or "")
                tasks.append(
                    {
                        "kind": "gpt-digest",
                        "status": "published",
                        "startedAt": stamp,
                        "finishedAt": stamp,
                        "error": None,
                        "ref": f"{row['config_id']}:{row['issue_key']}",
                    }
                )
        except Exception:  # noqa: BLE001
            pass

        try:
            row = await self._db.fetch_one(
                "SELECT last_sent_at, last_error FROM digest_settings WHERE id = 1"
            )
            if row is not None and (row["last_sent_at"] or row["last_error"]):
                stamp = str(row["last_sent_at"] or "")
                tasks.append(
                    {
                        "kind": "mail-digest",
                        "status": "failed" if row["last_error"] else "published",
                        "startedAt": stamp,
                        "finishedAt": stamp,
                        "error": row["last_error"],
                        "ref": "mail-digest",
                    }
                )
        except Exception:  # noqa: BLE001
            pass

        tasks.sort(key=lambda t: t["startedAt"], reverse=True)
        return tasks[: max(1, min(limit, 50))]
