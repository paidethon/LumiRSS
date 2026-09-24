"""Search projection storage — entry row writes.

Sync-time replaces run as one batched transaction per page (a rebuild of
thousands of rows used to pay one connection + commit per statement);
rebuild streams into a staging table via :meth:`stage_documents` and
swaps it in with :meth:`swap_staged` so a failed rebuild can never
strand a partial live index. The read/starred state mirrors for writes
made through the BFF stay single statements. All statements are inline
literals with bound parameters, matching the storage-layer convention.

N031/N032/N034/N040 intake capture (replace_entries, i.e. the incremental
projection update path):

- content hash change on the SAME item → one bounded revision row
  (metadata only: structural diff summary + hashes, never a content
  copy; cap 5 per entry, pruned at insert);
- content_max_len tracks the largest delivered content length; the
  retained long version lives in entry_content_variants (the ONE bounded
  content-bytes exception: keep_latest=1, ≤200 KB — the recovery choice
  needs the actual bytes);
- published_at credibility flags classified at ingest (bitmask);
- crawled_at keeps FreshRSS first-collection time (upstream provenance).

The full rebuild path (stage/swap) preserves content_max_len and
content_hash for known entries but does NOT write revisions or rotate
retained variants — a rebuild re-states the projection rather than
observing deliveries (documented boundary; entries indexed only by a
rebuild honestly degrade to hash-only summaries and "current only"
recovery until an incremental delivery passes the replace path).
"""

import json
import sqlite3

from .db_tx import transaction
from .entry_intake import (
    bound_title,
    classify_published_at,
    content_hash,
    revision_diff_summary,
)
from .models import EntryDocument
from .storage import Database

# N031: bounded revision history per entry (pruned at insert).
_REVISIONS_PER_ENTRY = 5
# N032: the retained-variant byte cap (rows above this are NOT retained;
# the trigger may still fire on content_max_len — recovery honestly
# degrades to "current only" when the long version was never retained).
_VARIANT_MAX_BYTES = 200 * 1024


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
        """Append one upstream page into the rebuild staging table.

        content_max_len is carried over from the live projection so the
        N032 trigger keeps its memory across rebuilds."""

        def _tx(conn: sqlite3.Connection) -> None:
            for doc, feed_url in zip(documents, feed_urls, strict=True):
                conn.execute(
                    "INSERT INTO search_rebuild_stage (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at, content_max_len, content_hash, time_flags, crawled_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, MAX(?, COALESCE((SELECT content_max_len FROM search_entries WHERE item_id = ?), 0)), ?, ?, ?)",
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
                        len(doc.contentHtml or ""),
                        doc.item_id,
                        content_hash(doc.contentHtml or ""),
                        classify_published_at(
                            doc.publishedAt or None, now_epoch=float(fetched_at)
                        ),
                        doc.crawledAt or None,
                    ),
                )

        await transaction(self._db, _tx)

    async def swap_staged(self) -> None:
        """Replace the live projection with the staged rows in ONE
        transaction — the swap is the rebuild's only destructive step."""

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM search_entries")
            conn.execute(
                "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at, content_max_len, content_hash, time_flags, crawled_at) SELECT item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at, content_max_len, content_hash, time_flags, crawled_at FROM search_rebuild_stage"
            )

        await transaction(self._db, _tx)

    async def replace_entries(
        self, documents: list[EntryDocument], *, feed_urls: list[str], fetched_at: int
    ) -> None:
        """Delete + insert these entries as one batched transaction, with
        N031/N032/N034/N040 intake capture (see module docstring)."""

        def _tx(conn: sqlite3.Connection) -> None:
            for doc, feed_url in zip(documents, feed_urls, strict=True):
                _replace_one(conn, doc, feed_url, fetched_at)

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


def _replace_one(
    conn: sqlite3.Connection, doc: EntryDocument, feed_url: str, fetched_at: int
) -> None:
    """One entry replace + bounded intake capture, inside the caller's tx."""
    new_html = doc.contentHtml or ""
    new_hash = content_hash(new_html)
    new_len = len(new_html)
    existing = conn.execute(
        "SELECT title, content_hash, content_max_len FROM search_entries WHERE item_id = ?",
        (doc.item_id,),
    ).fetchone()
    if existing is not None:
        _capture_variant_and_revision(
            conn,
            doc,
            new_html=new_html,
            new_hash=new_hash,
            new_len=new_len,
            prev_title=str(existing["title"] or ""),
            prev_hash=str(existing["content_hash"] or ""),
            prev_max=int(existing["content_max_len"] or 0),
            fetched_at=fetched_at,
        )
    else:
        # New entry via the incremental path: the first delivery IS the
        # initial known-full version candidate — retain it (bounded).
        _retain_variant(conn, doc.entryRef, new_html, new_len, fetched_at)
    conn.execute("DELETE FROM search_entries WHERE item_id = ?", (doc.item_id,))
    conn.execute(
        "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at, content_max_len, content_hash, time_flags, crawled_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            max(
                int(existing["content_max_len"] or 0) if existing is not None else 0,
                new_len,
            ),
            new_hash,
            classify_published_at(
                doc.publishedAt or None, now_epoch=float(fetched_at)
            ),
            doc.crawledAt or None,
        ),
    )


def _capture_variant_and_revision(
    conn: sqlite3.Connection,
    doc: EntryDocument,
    *,
    new_html: str,
    new_hash: str,
    new_len: int,
    prev_title: str,
    prev_hash: str,
    prev_max: int,
    fetched_at: int,
) -> None:
    """N031 revision + N032 retained variant, both bounded, both best-effort
    metadata operations that must never break the projection write."""
    if prev_hash == "":
        # Baseline establishment (first post-upgrade delivery): the first
        # full delivery IS the initial known-full version candidate —
        # retain it, but write no revision (nothing to diff against yet).
        _retain_variant(conn, doc.entryRef, new_html, new_len, fetched_at)
        return
    if prev_hash == new_hash:
        return  # unchanged delivery: no revision, no variant churn
    variant = conn.execute(
        "SELECT content_html, captured_at FROM entry_content_variants WHERE entry_ref = ?",
        (doc.entryRef,),
    ).fetchone()
    if variant is not None:
        summary = revision_diff_summary(
            str(variant["content_html"] or ""), new_html, basis="retained_variant"
        )
    else:
        summary = revision_diff_summary("", new_html, basis="hash_only")
    title_changed = bound_title(prev_title) != bound_title(doc.title)
    conn.execute(
        "INSERT INTO entry_revisions (entry_ref, captured_at, title_changed, prev_title, new_title, content_diff_summary, prev_hash, new_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            doc.entryRef,
            _utc_iso(fetched_at),
            1 if title_changed else 0,
            bound_title(prev_title),
            bound_title(doc.title),
            json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
            prev_hash,
            new_hash,
        ),
    )
    # Cap 5 per entry: prune everything older right after the insert.
    conn.execute(
        "DELETE FROM entry_revisions WHERE entry_ref = ? AND id NOT IN (SELECT id FROM entry_revisions WHERE entry_ref = ? ORDER BY id DESC LIMIT ?)",
        (doc.entryRef, doc.entryRef, _REVISIONS_PER_ENTRY),
    )
    # N032 retained long version: rotate keep_latest=1 only when THIS
    # delivery is the new largest; a shorter delivery never overwrites
    # the retained full version.
    _retain_variant(conn, doc.entryRef, new_html, new_len, fetched_at, prev_max=prev_max)


def _retain_variant(
    conn: sqlite3.Connection,
    entry_ref: str,
    new_html: str,
    new_len: int,
    fetched_at: int,
    *,
    prev_max: int | None = None,
) -> None:
    """Rotate the single retained long version (keep_latest=1, ≤200 KB).

    The byte cap is THE documented reason content bytes exist in this one
    side table: the recovery choice needs the actual bytes. Deliveries
    above the cap are never retained (recovery honestly degrades to
    "current only"); when prev_max is given, only a new-largest delivery
    may overwrite the retained version.
    """
    if not new_html or len(new_html.encode("utf-8")) > _VARIANT_MAX_BYTES:
        return
    if prev_max is not None and new_len < prev_max:
        return  # shorter delivery: the retained full version stays
    conn.execute(
        "INSERT INTO entry_content_variants (entry_ref, content_html, captured_at) VALUES (?, ?, ?) ON CONFLICT(entry_ref) DO UPDATE SET content_html = excluded.content_html, captured_at = excluded.captured_at",
        (entry_ref, new_html, _utc_iso(fetched_at)),
    )


def _utc_iso(epoch_seconds: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(epoch_seconds, tz=UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
