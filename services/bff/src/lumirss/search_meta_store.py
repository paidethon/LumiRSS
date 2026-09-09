"""Search projection storage — feed projection and sync metadata.

The feed -> category mirror is refreshed from the FreshRSS subscription
list at every sync so search can filter by category with one bound
parameter. Statements are inline literals with bound parameters.
"""

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

    async def meta_set(self, key: str, value: str) -> None:
        await self._db.execute(
            "INSERT INTO search_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
