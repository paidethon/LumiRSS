"""N039 附件失效检测 —— 读者上报的失效媒体（SQL 唯一入口）。

- 上报**非阻断**：记录失效事实（kind + src），绝不自动重试——本模块
  没有任何后台/隐式抓取路径；「单项重新加载」的 cache-bust 只发生在
  Web 读取侧（对 src 追加一次性参数），本表绝不改写 src；
- 幂等 upsert：``(entry_ref, kind, src)`` 唯一，重复上报仅刷新
  last_seen_at 与 hit_count（绝不翻倍成多行）；
- 有界：单次请求 ≤20 条（路由层强制）；每条目最多 50 行，超限按
  last_seen_at 最旧裁剪（插入时执行）。
"""

import sqlite3
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_PER_REQUEST = 20
_KEEP_PER_ENTRY = 50
_MAX_SRC_LENGTH = 2048
_KINDS = ("image", "media", "other")


class MediaFailureInvalid(Exception):
    """载荷非法（422 invalid_media_failures）。"""


def _clean(entry: dict[str, Any]) -> tuple[str, str]:
    kind = entry.get("kind")
    src = entry.get("src")
    if not isinstance(kind, str) or kind not in _KINDS:
        raise MediaFailureInvalid(f"kind 必须是 {'|'.join(_KINDS)} 之一。")
    if not isinstance(src, str) or not src.strip():
        raise MediaFailureInvalid("src 不能为空。")
    src = src.strip()
    if len(src) > _MAX_SRC_LENGTH:
        raise MediaFailureInvalid(f"src 最长 {_MAX_SRC_LENGTH} 字符。")
    return kind, src


class MediaFailureStore:
    """Persistence for entry_media_failures."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self, entry_ref: str, failures: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """批量 upsert（≤20/次）；返回记录后的全部失效列表。"""
        if len(failures) > _MAX_PER_REQUEST:
            raise MediaFailureInvalid(f"单次最多上报 {_MAX_PER_REQUEST} 条。")
        cleaned = [_clean(entry) for entry in failures]
        await self._db.migrate()
        now = utc_now()
        for kind, src in cleaned:
            await self._db.execute(
                "INSERT INTO entry_media_failures (entry_ref, kind, src, first_seen_at, last_seen_at, hit_count)"
                " VALUES (?, ?, ?, ?, ?, 1)"
                " ON CONFLICT(entry_ref, kind, src) DO UPDATE SET"
                " last_seen_at = excluded.last_seen_at, hit_count = hit_count + 1",
                (entry_ref, kind, src, now, now),
            )
        if cleaned:
            await self._prune(entry_ref)
        return await self.list_failures(entry_ref)

    async def _prune(self, entry_ref: str) -> None:
        await self._db.execute(
            "DELETE FROM entry_media_failures WHERE entry_ref = ? AND id NOT IN ("
            " SELECT id FROM entry_media_failures WHERE entry_ref = ?"
            " ORDER BY last_seen_at DESC, id DESC LIMIT ?)",
            (entry_ref, entry_ref, _KEEP_PER_ENTRY),
        )

    async def list_failures(self, entry_ref: str) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT kind, src, first_seen_at, last_seen_at, hit_count"
            " FROM entry_media_failures WHERE entry_ref = ?"
            " ORDER BY last_seen_at DESC, id DESC",
            (entry_ref,),
        )
        return [
            {
                "kind": str(row["kind"]),
                "src": str(row["src"]),
                "firstSeenAt": str(row["first_seen_at"]),
                "lastSeenAt": str(row["last_seen_at"]),
                "hitCount": int(row["hit_count"]),
            }
            for row in rows
        ]

    async def clear(self, entry_ref: str) -> None:
        await self._db.migrate()

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM entry_media_failures WHERE entry_ref = ?", (entry_ref,)
            )

        await transaction(self._db, _tx)
