"""F063 AI 任务中心 — AI 生成任务的尽力而为埋点与查询。

- 埋点契约：record/record_best_effort 绝不抛出、绝不阻塞主流程；
  埋点自身失败一律吞掉（任务日志是诊断增强，不是关键路径）。
- 诚实口径：status 反映真实结果（服务返回失败状态 → failed；
  provider 异常 → failed + error_type=异常类型名）；未知字段留空，
  绝不编造。
- 存储：记录时裁剪到最近 500 条（有界）；读取默认/上限由路由限定。

全部 SQL 为内联字面量 + 绑定参数；写站点 2 处（INSERT + 裁剪 DELETE）。
"""

import time
import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

TASK_KINDS = (
    "summary",
    "translation",
    "conversation",
    "quiz",
    "cards",
    "compare",
    "ask_batch",
)

_MAX_ROWS = 500
_MAX_ERRORS = 50

_INSERT_SQL = """INSERT INTO ai_task_log (
id, kind, entry_ref, status, model, duration_ms, input_chars, error_type,
created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""

_PRUNE_SQL = """DELETE FROM ai_task_log WHERE rowid NOT IN (
SELECT rowid FROM ai_task_log ORDER BY created_at DESC, rowid DESC LIMIT ?)"""


class AiTaskLogStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        *,
        kind: str,
        status: str,
        entry_ref: str | None = None,
        model: str = "",
        duration_ms: int = 0,
        input_chars: int | None = None,
        error_type: str | None = None,
    ) -> str:
        await self._db.migrate()
        task_id = str(_uuid.uuid4())
        await self._db.execute(
            _INSERT_SQL,
            (
                task_id,
                kind,
                entry_ref,
                status,
                model,
                max(0, int(duration_ms)),
                input_chars,
                (error_type or "")[:200] or None,
                utc_now(),
            ),
        )
        await self._db.execute(_PRUNE_SQL, (_MAX_ROWS,))
        return task_id

    async def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            """SELECT id, kind, entry_ref, status, model, duration_ms,
            input_chars, error_type, created_at FROM ai_task_log
            ORDER BY created_at DESC, rowid DESC LIMIT ?""",
            (max(1, min(limit, _MAX_ERRORS + 50)),),
        )
        return [_row(row) for row in rows]

    async def get(self, task_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            """SELECT id, kind, entry_ref, status, model, duration_ms,
            input_chars, error_type, created_at FROM ai_task_log WHERE id = ?""",
            (task_id,),
        )
        return _row(row) if row is not None else None

    async def count_before(self, cutoff: str) -> int:
        """N189 活动清除预览：早于 cutoff（ISO 文本比较口径）的条数。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM ai_task_log WHERE created_at < ?",
            (cutoff,),
        )
        return int(row["n"]) if row else 0

    async def purge_before(self, cutoff: str) -> int:
        """N189 活动清除：删除早于 cutoff 的任务记录，返回删除数。

        只动 ai_task_log（诊断埋点）——业务状态（已读/收藏/笔记）不在
        本表，天然不受影响。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM ai_task_log WHERE created_at < ?",
            (cutoff,),
        )
        await self._db.execute(
            "DELETE FROM ai_task_log WHERE created_at < ?",
            (cutoff,),
        )
        return int(row["n"]) if row else 0


def _row(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "kind": str(row["kind"]),
        "entryRef": row["entry_ref"],
        "status": str(row["status"]),
        "model": str(row["model"] or ""),
        "durationMs": int(row["duration_ms"] or 0),
        "inputChars": row["input_chars"],
        "errorType": row["error_type"],
        "createdAt": str(row["created_at"]),
    }


async def record_best_effort(db: Database, **kwargs: Any) -> str | None:
    """埋点入口：吞掉一切异常，绝不影响主流程。返回任务 id（失败 None）。"""
    try:
        return await AiTaskLogStore(db).record(**kwargs)
    except Exception:  # noqa: BLE001 — 埋点失败静默（诊断增强非关键路径）
        return None


async def resolve_model(db: Database) -> str:
    """当前 AI 模型（设置不可用时留空——诚实，不编造）。"""
    try:
        from lumirss.ai_settings import KEY_MODEL, AiSettingsStore

        return str((await AiSettingsStore(db).load()).get(KEY_MODEL) or "")
    except Exception:  # noqa: BLE001
        return ""


class TaskTimer:
    """duration 计时（monotonic，不受系统时钟回拨影响）。"""

    def __init__(self) -> None:
        self._start = time.monotonic()

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._start) * 1000)
