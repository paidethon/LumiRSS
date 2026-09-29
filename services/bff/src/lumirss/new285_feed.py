"""NEW-285 个人简报 RSS 发布 —— 确认期次的可撤销私有 Atom 订阅。

- 每用户一份 feed 凭据：enable（明文只在响应出现一次，库存 SHA-256
  哈希，token_hash.py 同一口径）/ rotate（旧 token 立即失效）/
  revoke（撤销 → 公开路由与错 token 同一 404，不泄露存在性）；
- 公开路由 GET /feeds/briefings/{token}.atom 免登录，经
  machine_user_context 解析归属用户后只渲染「已确认」期次；草稿绝不
  进 feed；
- 内容边界：每期 = 摘要卡列表（标题/来源/链接/摘录 + 编辑来源标记
  287）+ 更正提示（290，只追加）。本组条目不存任何私人笔记，feed
  结构上就没有可自动公开的原始私人笔记。
"""

import secrets
import sqlite3
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.token_hash import hash_token, verify_token
from lumirss.util import utc_now


class FeedTokenStateConflict(Exception):
    """feed 凭据已存在/未启用等状态冲突（映射 409）。"""


class BriefingFeedStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_state(self) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, token_hash, enabled, created_at, rotated_at, revoked_at"
            " FROM briefing_feed_tokens WHERE id = 'default'"
        )
        if row is None:
            return None
        return {
            "enabled": bool(row["enabled"]) and row["revoked_at"] is None,
            "createdAt": str(row["created_at"]),
            "rotatedAt": str(row["rotated_at"] or "") or None,
            "revokedAt": str(row["revoked_at"] or "") or None,
        }

    async def enable(self) -> dict[str, Any]:
        """首次启用：生成明文 token（响应一次性返回）。"""
        await self._db.migrate()
        state = await self.get_state()
        if state is not None and state["enabled"]:
            raise FeedTokenStateConflict("feed 已启用（轮换请用 rotate，撤销用 revoke）。")
        raw = secrets.token_hex(16)
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM briefing_feed_tokens WHERE id = 'default'"
            )
            conn.execute(
                "INSERT INTO briefing_feed_tokens (id, token_hash, enabled,"
                " created_at) VALUES ('default', ?, 1, ?)",
                (hash_token(raw), now),
            )

        await transaction(self._db, _tx)
        return {
            "token": raw,
            "path": f"/feeds/briefings/{raw}.atom",
            "createdAt": now,
        }

    async def rotate(self) -> dict[str, Any]:
        state = await self._require_enabled()
        if state is None:
            raise FeedTokenStateConflict("feed 未启用。")
        raw = secrets.token_hex(16)
        now = utc_now()
        await self._db.execute(
            "UPDATE briefing_feed_tokens SET token_hash = ?, rotated_at = ?"
            " WHERE id = 'default'",
            (hash_token(raw), now),
        )
        return {
            "token": raw,
            "path": f"/feeds/briefings/{raw}.atom",
            "rotatedAt": now,
        }

    async def revoke(self) -> bool:
        state = await self._require_enabled()
        if state is None:
            return False
        await self._db.execute(
            "UPDATE briefing_feed_tokens SET enabled = 0, revoked_at = ?"
            " WHERE id = 'default'",
            (utc_now(),),
        )
        return True

    async def verify(self, presented: str) -> bool:
        """公开路由校验：哈希比对 + 仍启用。"""
        row = await self._db.fetch_one(
            "SELECT token_hash, enabled, revoked_at FROM briefing_feed_tokens"
            " WHERE id = 'default'"
        )
        if row is None:
            return False
        if not bool(row["enabled"]) or row["revoked_at"] is not None:
            return False
        return verify_token(presented, str(row["token_hash"]))

    async def _require_enabled(self) -> dict[str, Any] | None:
        state = await self.get_state()
        if state is None or not state["enabled"]:
            return None
        return state
