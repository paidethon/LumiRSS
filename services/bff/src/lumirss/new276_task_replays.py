"""NEW-276 AI 失败重放诊断 —— 失败任务的脱敏诊断与两种重试路径。

- 诊断从 ai_task_log 行派生：kind / model / input_chars / duration_ms /
  error_type + 按 kind 合成的请求结构（端点族、entryRef、边界参数）。
  文章正文与问题内容从不入库，因此也绝不出现在诊断里（脱敏是结构性
  的，不是事后擦除）；
- mode="same"：用相同配置重试。只有摘要可原样重放（缓存服务按身份
  重新生成）；conversation 的任务日志不含问题正文（不可重建），
  mode="same" 诚实拒绝并提示「修改后新建」；
- mode="modified"：修改参数后新建任务（summary 可带新 maxChars；
  conversation 必须提供新问题）；
- 每次重放记录血缘（ai_task_replays：original → replay, mode）。

per-user：任务日志与血缘在 per-user 库，A 的失败任务对 B 不可见。
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from lumirss.ai_task_log import AiTaskLogStore
from lumirss.storage import Database
from lumirss.util import utc_now

REPLAYABLE_KINDS = ("summary",)
_MAX_MODES = ("same", "modified")


class ReplayNotFound(Exception):
    """任务不存在（映射 404）。"""


class ReplayNotAvailable(Exception):
    """该任务不能按请求的方式重放（映射 422），携带诚实原因。"""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class ReplayStore:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._tasks = AiTaskLogStore(db)

    async def diagnostic(self, task_id: str) -> dict[str, Any]:
        """脱敏诊断：结构字段 + 按 kind 合成的请求形状（无内容）。"""
        task = await self._tasks.get(task_id)
        if task is None:
            raise ReplayNotFound(task_id)
        if task["status"] != "failed":
            raise ReplayNotAvailable(
                "task_not_failed", "只有失败任务有重放诊断。"
            )
        kind = task["kind"]
        if kind == "conversation":
            shape: dict[str, Any] = {
                "endpoint": "/api/v1/entries/{entryRef}/conversation/messages",
                "boundedFields": ["question(≤4000 chars)", "maxChars(512–50000)"],
                "note": (
                    "问题正文不入库（失败不持久化），无法原样重放；"
                    "请用 mode=modified 提供新问题。"
                ),
            }
        elif kind == "summary":
            shape = {
                "endpoint": "/api/v1/entries/{entryRef}/summary",
                "boundedFields": ["maxChars(512–50000，可选)"],
                "note": "正文按内容哈希定位，不随诊断展示。",
            }
        else:
            shape = {
                "endpoint": f"(kind={kind})",
                "boundedFields": [],
                "note": "该任务类型没有通用重放端点；诊断仅记录结构字段。",
            }
        entry_ref = task["entryRef"]
        if entry_ref:
            shape["entryRef"] = entry_ref
        return {
            **task,
            "requestShape": shape,
            "redactionNote": (
                "诊断只含结构字段（类型/模型/用量/错误分类）；"
                "文章正文与问题内容从不入库，因此不出现在诊断里。"
            ),
            "replayModes": _replay_modes(kind),
        }

    async def replay(
        self,
        task_id: str,
        *,
        mode: str,
        run: Callable[[dict[str, Any]], Awaitable[str]],
    ) -> dict[str, Any]:
        """按 mode 重放并记录血缘；run(diagnostic) → 新任务 id。"""
        if mode not in _MAX_MODES:
            raise ReplayNotAvailable("invalid_mode", "mode 必须是 same 或 modified。")
        diagnostic = await self.diagnostic(task_id)
        kind = diagnostic["kind"]
        if mode == "same" and kind not in REPLAYABLE_KINDS:
            raise ReplayNotAvailable(
                "not_replayable_same",
                f"{kind} 任务无法原样重放（必要输入未持久化）；"
                "请选择 mode=modified 修改后新建。",
            )
        if mode == "modified" and kind == "conversation":
            # 新问题由 run 回调校验（缺失 → 422），这里不假设形状。
            pass
        replay_task_id = await run(diagnostic)
        replay_id = uuid.uuid4().hex[:20]
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO ai_task_replays (id, original_task_id, replay_task_id, "
            "mode, created_at) VALUES (?, ?, ?, ?, ?)",
            (replay_id, task_id, replay_task_id, mode, utc_now()),
        )
        return {
            "replayId": replay_id,
            "originalTaskId": task_id,
            "replayTaskId": replay_task_id,
            "mode": mode,
            "createdAt": utc_now(),
        }

    async def list_replays(self, task_id: str) -> list[dict[str, Any]]:
        """一个原始失败任务的全部重放血缘（新→旧）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, original_task_id, replay_task_id, mode, created_at "
            "FROM ai_task_replays WHERE original_task_id = ? "
            "ORDER BY created_at DESC, rowid DESC",
            (task_id,),
        )
        return [
            {
                "id": str(row["id"]),
                "originalTaskId": str(row["original_task_id"]),
                "replayTaskId": str(row["replay_task_id"]),
                "mode": str(row["mode"]),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]


def _replay_modes(kind: str) -> list[dict[str, str]]:
    modes = [
        {
            "mode": "modified",
            "hint": (
                "conversation 需要新问题；summary 可带新 maxChars。"
                if kind == "conversation"
                else "可带新的 maxChars 后新建任务。"
            ),
        }
    ]
    if kind in REPLAYABLE_KINDS:
        modes.insert(
            0,
            {"mode": "same", "hint": "用相同配置重试（同一文章、同一设置）。"},
        )
    return modes
