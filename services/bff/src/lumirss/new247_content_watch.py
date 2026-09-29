"""NEW-247 原文变动关注 —— 关注 + 显式哈希比对检测 + 差异入口。

语义边界（模块存在的理由）：

- 关注：用户提交基线正文（POST），sha256 落库；每篇至多一条关注
  （UNIQUE，重复关注 → 409，先删旧关注再关注）；
- 检测：用户提交当前正文（POST check），与基线哈希**显式比对**——
  相同 → 仍 watching（记 last_checked_at，checks_count+1）；
  不同 → changed（把当前正文存下，供差异使用）。系统不主动抓取
  上游（没有后台爬虫），「实际检测到变化」= 这次提交的正文与基线
  不同这一事实，不是预测也不是推断；
- 差异入口：changed 之后 GET diff 返回基线 vs 检测到的当前的段落级
  差异（复用 NEW-241 的 diff_paragraphs 纯函数）；watching 状态请求
  差异 → 409（诚实：还没有变化可差异）。

per-user 库：关注天然按账户隔离。
"""

import hashlib
import sqlite3
import uuid as _uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.new241_article_versions import diff_paragraphs
from lumirss.storage import Database
from lumirss.util import utc_now

_TEXT_MAX = 200_000


class WatchInvalid(ValueError):
    """关注负载非法（映射 422）。"""


class WatchConflict(Exception):
    """重复关注（映射 409）。"""


class WatchNotFound(Exception):
    """没有关注记录（映射 404）。"""


class WatchNotChanged(Exception):
    """仍在 watching，无变化可差异（映射 409）。"""


def _validate_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WatchInvalid(f"{field} 不能为空。")
    if len(value) > _TEXT_MAX:
        raise WatchInvalid(f"{field} 超出 {_TEXT_MAX} 字符上限。")
    return value


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ContentWatchStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _validate_entry_ref(entry_ref: Any) -> str:
        if not isinstance(entry_ref, str) or not 1 <= len(entry_ref) <= 300:
            raise WatchInvalid("entry_ref 非法。")
        return entry_ref

    # -- 关注 ----------------------------------------------------------------

    async def watch(self, entry_ref: str, baseline_text: str) -> dict[str, Any]:
        clean_ref = self._validate_entry_ref(entry_ref)
        clean_text = _validate_text(baseline_text, "baselineText")
        await self._db.migrate()
        existing = await self._db.fetch_one(
            "SELECT id FROM content_watches WHERE entry_ref = ?", (clean_ref,)
        )
        if existing is not None:
            raise WatchConflict(clean_ref)
        watch_id = str(_uuid.uuid4())
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO content_watches (id, entry_ref, baseline_sha256, baseline_text, status, created_at) "
                "VALUES (?, ?, ?, ?, 'watching', ?)",
                (watch_id, clean_ref, _sha256(clean_text), clean_text, now),
            )

        await transaction(self._db, _tx)
        return {
            "id": watch_id,
            "entryRef": clean_ref,
            "baselineSha256": _sha256(clean_text),
            "baselineChars": len(clean_text),
            "status": "watching",
            "createdAt": now,
        }

    async def get_watch(self, entry_ref: str) -> dict[str, Any]:
        clean_ref = self._validate_entry_ref(entry_ref)
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, baseline_sha256, status, current_text, changed_at, last_checked_at, "
            "checks_count, created_at, LENGTH(baseline_text) AS baseline_chars "
            "FROM content_watches WHERE entry_ref = ?",
            (clean_ref,),
        )
        if row is None:
            raise WatchNotFound(clean_ref)
        return {
            "id": str(row["id"]),
            "entryRef": clean_ref,
            "baselineSha256": str(row["baseline_sha256"]),
            "baselineChars": int(row["baseline_chars"] or 0),
            "status": str(row["status"]),
            "changedAt": str(row["changed_at"]) if row["changed_at"] else None,
            "lastCheckedAt": str(row["last_checked_at"]) if row["last_checked_at"] else None,
            "checksCount": int(row["checks_count"]),
            "createdAt": str(row["created_at"]),
        }

    async def unwatch(self, entry_ref: str) -> None:
        clean_ref = self._validate_entry_ref(entry_ref)
        await self._db.migrate()

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM content_watches WHERE entry_ref = ?", (clean_ref,))

        await transaction(self._db, _tx)

    # -- 检测 ----------------------------------------------------------------

    async def check(self, entry_ref: str, current_text: str) -> dict[str, Any]:
        """提交当前正文 → 与基线哈希显式比对。"""
        clean_ref = self._validate_entry_ref(entry_ref)
        clean_text = _validate_text(current_text, "currentText")
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, baseline_sha256, status FROM content_watches WHERE entry_ref = ?",
            (clean_ref,),
        )
        if row is None:
            raise WatchNotFound(clean_ref)
        now = utc_now()
        changed = _sha256(clean_text) != str(row["baseline_sha256"])
        status = "changed" if changed else "watching"

        def _tx(conn: sqlite3.Connection) -> None:
            if changed:
                conn.execute(
                    "UPDATE content_watches SET status = 'changed', current_text = ?, "
                    "changed_at = ?, last_checked_at = ?, checks_count = checks_count + 1 "
                    "WHERE id = ?",
                    (clean_text, now, now, str(row["id"])),
                )
            else:
                conn.execute(
                    "UPDATE content_watches SET last_checked_at = ?, checks_count = checks_count + 1 "
                    "WHERE id = ?",
                    (now, str(row["id"])),
                )

        await transaction(self._db, _tx)
        return {
            "entryRef": clean_ref,
            "status": status,
            "changed": changed,
            "checkedAt": now,
        }

    async def diff(self, entry_ref: str) -> dict[str, Any]:
        """changed 之后：基线 vs 检测到的当前的段落级差异。"""
        clean_ref = self._validate_entry_ref(entry_ref)
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT baseline_text, current_text, status, changed_at FROM content_watches WHERE entry_ref = ?",
            (clean_ref,),
        )
        if row is None:
            raise WatchNotFound(clean_ref)
        if str(row["status"]) != "changed" or row["current_text"] is None:
            raise WatchNotChanged(clean_ref)
        result = diff_paragraphs(str(row["baseline_text"]), str(row["current_text"]))
        return {
            "entryRef": clean_ref,
            "baseline": "baseline",
            "current": "detected",
            "changedAt": str(row["changed_at"]),
            **result,
        }
