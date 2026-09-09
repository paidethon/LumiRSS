"""Search projection storage — entry row writes.

Delete + insert per entry (the projection is derived data, so the pair
does not need to be transactional — a crash mid-way self-heals on the
next sync) and the read/starred state mirrors for writes made through
the BFF. All statements are inline literals with bound parameters,
matching the storage-layer convention.
"""

from .storage import Database


class SearchEntryWriter:
    """Write path for projected entry rows."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def delete_entry(self, item_id: str) -> None:
        await self._db.execute(
            "DELETE FROM search_entries WHERE item_id = ?", (item_id,)
        )

    async def insert_entry(
        self,
        *,
        item_id: str,
        entry_ref: str,
        feed_url: str,
        feed_title: str,
        title: str,
        author: str,
        url: str,
        content_text: str,
        published_at: str,
        read: int,
        starred: int,
        fetched_at: int,
    ) -> None:
        await self._db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item_id,
                entry_ref,
                feed_url,
                feed_title,
                title,
                author,
                url,
                content_text,
                published_at,
                read,
                starred,
                fetched_at,
            ),
        )

    async def set_read(self, entry_ref: str, read: int) -> None:
        await self._db.execute(
            "UPDATE search_entries SET read = ? WHERE entry_ref = ?",
            (read, entry_ref),
        )

    async def set_starred(self, entry_ref: str, starred: int) -> None:
        await self._db.execute(
            "UPDATE search_entries SET starred = ? WHERE entry_ref = ?",
            (starred, entry_ref),
        )
