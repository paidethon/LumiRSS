"""Search projection storage — feed projection and sync metadata.

The feed -> category mirror is refreshed from the FreshRSS subscription
list at every sync so search can filter by category with one bound
parameter. Statements are inline literals with bound parameters.
"""

import sqlite3

from .db_tx import transaction
from .storage import Database


class SearchFeedStore:
    """Feed projection and sync-metadata writes."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def clear_feeds(self) -> None:
        await self._db.execute("DELETE FROM search_feeds")

    async def insert_feed(
        self,
        *,
        feed_url: str,
        feed_title: str,
        category_id: str | None,
        refreshed_at: int,
    ) -> None:
        await self._db.execute(
            "INSERT INTO search_feeds (feed_url, feed_title, category_id, refreshed_at) VALUES (?, ?, ?, ?)",
            (feed_url, feed_title, category_id, refreshed_at),
        )

    async def replace_feeds(self, feeds: list, *, refreshed_at: int) -> None:
        """Rewrite the whole feed mirror in one transaction (one commit
        per sync instead of one per feed)."""

        def _tx(conn: sqlite3.Connection) -> None:
            for feed in feeds:
                conn.execute(
                    "INSERT INTO search_feeds (feed_url, feed_title, category_id, refreshed_at) VALUES (?, ?, ?, ?)",
                    (feed.feed_url, feed.title, feed.category_id, refreshed_at),
                )

        await transaction(self._db, _tx)

    async def meta_set(self, key: str, value: str) -> None:
        # House rule: no UPSERT — explicit SELECT-then-INSERT/UPDATE.
        # A concurrent writer winning the INSERT race (IntegrityError)
        # converges via the UPDATE retry instead of surfacing a 500.
        existing = await self._db.fetch_one(
            "SELECT key FROM search_meta WHERE key = ?", (key,)
        )
        if existing is not None:
            await self._db.execute(
                "UPDATE search_meta SET value = ? WHERE key = ?",
                (value, key),
            )
            return
        try:
            await self._db.execute(
                "INSERT INTO search_meta (key, value) VALUES (?, ?)",
                (key, value),
            )
        except sqlite3.IntegrityError:
            await self._db.execute(
                "UPDATE search_meta SET value = ? WHERE key = ?",
                (value, key),
            )
