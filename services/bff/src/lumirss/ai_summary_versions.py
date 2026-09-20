"""F027 摘要版本 —— ai_summary_versions 的 SQL 唯一入口。

- 同一 (entry_ref, content_hash) 重生成保留旧版本：每键最多 3 版，
  FIFO 淘汰最旧；
- 只有成功生成才落版（既有失败语义保持：失败不覆盖、不产生新版本）；
- activate = 把所选版本的正文写回当前 ai_summaries 行（切换展示），
  引用集/缓存身份不变。
"""

import uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_VERSIONS = 3


class SummaryVersionNotFound(Exception):
    """版本不存在（404）。"""


_COLUMNS = "id, entry_ref, content_hash, summary, provider, model, created_at"


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "versionId": str(row["id"]),
        "entryRef": str(row["entry_ref"]),
        "contentHash": str(row["content_hash"]),
        "summary": str(row["summary"]),
        "provider": str(row["provider"]),
        "model": str(row["model"]),
        "createdAt": str(row["created_at"]),
    }


class SummaryVersionStore:
    """版本落库 / 列表 / 切换（内联 SQL + 绑定参数；写站点 ≤4）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record_version(
        self,
        *,
        entry_ref: str,
        content_hash: str,
        summary: str,
        provider: str,
        model: str,
    ) -> dict[str, Any]:
        await self._db.migrate()
        version_id = f"sv-{uuid.uuid4().hex[:20]}"
        await self._db.execute(
            "INSERT INTO ai_summary_versions (id, entry_ref, content_hash, summary, provider, model, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (version_id, entry_ref, content_hash, summary, provider, model, utc_now()),
        )
        # FIFO 淘汰：保留最新 _MAX_VERSIONS 版（seq 降序第 N-3 之后的旧版删除）。
        stale = await self._db.fetch_all(
            "SELECT id FROM ai_summary_versions WHERE entry_ref = ? AND content_hash = ? ORDER BY seq DESC LIMIT -1 OFFSET ?",
            (entry_ref, content_hash, _MAX_VERSIONS),
        )
        for row in stale:
            await self._db.execute(
                "DELETE FROM ai_summary_versions WHERE id = ?", (row["id"],)
            )
        created = await self._db.fetch_one(
            f"SELECT {_COLUMNS} FROM ai_summary_versions WHERE id = ?",
            (version_id,),
        )
        assert created is not None
        return _row_to_dict(created)

    async def list_versions(
        self, entry_ref: str, content_hash: str
    ) -> list[dict[str, Any]]:
        """旧→新。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            f"SELECT {_COLUMNS} FROM ai_summary_versions WHERE entry_ref = ? AND content_hash = ? ORDER BY seq ASC",
            (entry_ref, content_hash),
        )
        return [_row_to_dict(row) for row in rows]

    async def get_version(self, version_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            f"SELECT {_COLUMNS} FROM ai_summary_versions WHERE id = ?",
            (version_id,),
        )
        return _row_to_dict(row) if row is not None else None

    async def activate(
        self, entry_ref: str, identity_params: tuple, version_id: str
    ) -> dict[str, Any] | None:
        """把所选版本写回当前成功行（不删任何版本）。行不存在 → None。"""
        version = await self.get_version(version_id)
        if version is None or version["entryRef"] != entry_ref:
            return None
        await self._db.migrate()
        exists = await self._db.fetch_one(
            "SELECT id FROM ai_summaries WHERE entry_ref = ? AND content_hash = ? "
            "AND provider = ? AND model = ? AND prompt_version = ? AND language = ?",
            identity_params,
        )
        if exists is None:
            return None
        await self._db.execute(
            "UPDATE ai_summaries SET summary_text = ?, updated_at = ? "
            "WHERE entry_ref = ? AND content_hash = ? AND provider = ? "
            "AND model = ? AND prompt_version = ? AND language = ?",
            (version["summary"], utc_now(), *identity_params),
        )
        return version
