"""F069 文章阅读自测 — 会话式 quiz（生成/评分/过期清理）。

- 表 quiz_sessions（迁移 0055）：payload_json 只存题目（无答案）；
  answers_json 存答案+解析+证据（评分路径专用，生成响应绝不返回）；
- 证据核验：evidence_quote 必须存在于条目正文（规范化子串匹配，
  与 F067 同口径），不匹配的题整题丢弃；全部被丢 → 422；
- 过期：>24h 的会话在生成时顺带清理；过期/不存在会话评分 → 404；
- 条目删除后会话残留无害（评分不再触达 FreshRSS，仅读本表）。

全部 SQL 为内联字面量 + 绑定参数；写站点 2 处（INSERT + 过期清理）。
"""

import json as _json
import uuid as _uuid
from dataclasses import dataclass
from typing import Any

from lumirss.util import utc_now

SESSION_TTL_HOURS = 24
MIN_CONTENT_CHARS = 400

_INSERT_SQL = """INSERT INTO quiz_sessions (
id, entry_ref, payload_json, answers_json, created_at)
VALUES (?, ?, ?, ?, ?)"""

_CLEAN_SQL = """DELETE FROM quiz_sessions WHERE created_at < ?"""

_GET_SQL = """SELECT id, entry_ref, payload_json, answers_json, created_at
FROM quiz_sessions WHERE id = ?"""


@dataclass(frozen=True)
class QuizQuestion:
    """一道已核验的题目（含答案，仅落库/评分使用）。"""

    index: int
    question: str
    options: list[str]
    answer_index: int
    explanation: str
    evidence_quote: str


def session_row_to_public(row: dict[str, Any]) -> dict[str, Any]:
    """payload_json → 对外题目视图（绝不含答案字段）。"""
    payload = _json.loads(row["payload_json"])
    return {
        "quizId": str(row["id"]),
        "entryRef": str(row["entry_ref"]),
        "createdAt": str(row["created_at"]),
        "questions": [
            {"index": q["index"], "question": q["question"], "options": q["options"]}
            for q in payload
        ],
    }


def answers_of(row: dict[str, Any]) -> list[dict[str, Any]]:
    return list(_json.loads(row["answers_json"]))


class QuizSessionStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def create(
        self, entry_ref: str, questions: list[QuizQuestion]
    ) -> dict[str, Any]:
        await self._db.migrate()
        quiz_id = str(_uuid.uuid4())
        now = utc_now()
        payload = _json.dumps(
            [
                {
                    "index": q.index,
                    "question": q.question,
                    "options": q.options,
                }
                for q in questions
            ],
            ensure_ascii=False,
        )
        answers = _json.dumps(
            [
                {
                    "index": q.index,
                    "answerIndex": q.answer_index,
                    "explanation": q.explanation,
                    "evidenceQuote": q.evidence_quote,
                }
                for q in questions
            ],
            ensure_ascii=False,
        )
        await self._db.execute(_INSERT_SQL, (quiz_id, entry_ref, payload, answers, now))
        # 读取路径顺带清理过期会话（>24h）
        from datetime import datetime, timedelta

        cutoff = (datetime.now() - timedelta(hours=SESSION_TTL_HOURS)).isoformat(
            timespec="seconds"
        )
        await self._db.execute(_CLEAN_SQL, (cutoff,))
        row = await self._db.fetch_one(_GET_SQL, (quiz_id,))
        return dict(row) if row is not None else {}

    async def get(self, quiz_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(_GET_SQL, (quiz_id,))
        return dict(row) if row is not None else None
