"""Search projection storage — entry row writes.

Sync-time replaces run as one batched transaction per page (a rebuild of
thousands of rows used to pay one connection + commit per statement);
rebuild streams into a staging table via :meth:`stage_documents` and
swaps it in with :meth:`swap_staged` so a failed rebuild can never
strand a partial live index. The read/starred state mirrors for writes
made through the BFF stay single statements. All statements are inline
literals with bound parameters, matching the storage-layer convention.
"""

import sqlite3

from .db_tx import transaction
from .models import EntryDocument
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

    async def stage_documents(
        self,
        documents: list[EntryDocument],
        *,
        feed_urls: list[str],
        fetched_at: int,
    ) -> None:
        """Append one upstream page into the rebuild staging table."""

        def _tx(conn: sqlite3.Connection) -> None:
            for doc, feed_url in zip(documents, feed_urls, strict=True):
                conn.execute(
                    "INSERT INTO search_rebuild_stage (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        doc.item_id,
                        doc.entryRef,
                        feed_url,
                        doc.feedTitle,
                        doc.title,
                        doc.author or "",
                        doc.url or "",
                        doc.contentText,
                        doc.publishedAt,
                        int(doc.read),
                        int(doc.starred),
                        fetched_at,
                    ),
                )

        await transaction(self._db, _tx)

    async def swap_staged(self) -> None:
        """Replace the live projection with the staged rows in ONE
        transaction — the swap is the rebuild's only destructive step."""

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM search_entries")
            conn.execute(
                "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) SELECT item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at FROM search_rebuild_stage"
            )

        await transaction(self._db, _tx)

    async def replace_entries(
        self, documents: list[EntryDocument], *, feed_urls: list[str], fetched_at: int
    ) -> None:
        """Delete + insert these entries as one batched transaction."""

        def _tx(conn: sqlite3.Connection) -> None:
            for doc, feed_url in zip(documents, feed_urls, strict=True):
                conn.execute(
                    "DELETE FROM search_entries WHERE item_id = ?",
                    (doc.item_id,),
                )
                conn.execute(
                    "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        doc.item_id,
                        doc.entryRef,
                        feed_url,
                        doc.feedTitle,
                        doc.title,
                        doc.author or "",
                        doc.url or "",
                        doc.contentText,
                        doc.publishedAt,
                        int(doc.read),
                        int(doc.starred),
                        fetched_at,
                    ),
                )

        await transaction(self._db, _tx)

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
