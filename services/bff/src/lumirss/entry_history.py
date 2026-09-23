"""Entry history reads — revisions (N031) and content variants (N032).

Read side of the bounded intake records written by the projection update
path (search_writer). All statements are inline literals with bound
parameters; every read degrades honestly (missing rows → None / empty).
"""

from typing import Any

from lumirss.entry_intake import decode_summary, time_flag_codes
from lumirss.models import ContentVariantOption, ContentVariantsBlock, EntryRevision
from lumirss.storage import Database

# N032 trigger threshold: current content must be shorter than 40% of the
# largest previously-seen variant to offer recovery choices.
_TRIGGER_RATIO = 0.4

_VARIANT_LABELS = {"current": "上游当前", "last_known_full": "上次完整版本"}


class EntryHistoryStore:
    """Read path over entry_revisions / entry_content_variants."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def revisions(self, entry_ref: str, *, limit: int = 20) -> list[EntryRevision]:
        """Bounded revision list, newest first (server cap also bounds it)."""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, captured_at, title_changed, prev_title, new_title, content_diff_summary, prev_hash, new_hash FROM entry_revisions WHERE entry_ref = ? ORDER BY id DESC LIMIT ?",
            (entry_ref, limit),
        )
        return [
            EntryRevision(
                id=int(row["id"]),
                capturedAt=str(row["captured_at"]),
                titleChanged=bool(row["title_changed"]),
                prevTitle=(str(row["prev_title"]) or None) if row["prev_title"] else None,
                newTitle=(str(row["new_title"]) or None) if row["new_title"] else None,
                summary=decode_summary(row["content_diff_summary"]),
                prevHash=str(row["prev_hash"] or ""),
                newHash=str(row["new_hash"] or ""),
            )
            for row in rows
        ]

    async def intake_meta(self, entry_refs: list[str]) -> dict[str, dict[str, Any]]:
        """entry_ref → {timeFlags, fetchedAt} for one bounded page."""
        await self._db.migrate()
        if not entry_refs:
            return {}
        placeholders = ",".join("?" for _ in entry_refs)
        rows = await self._db.fetch_all(
            f"SELECT entry_ref, time_flags, fetched_at FROM search_entries WHERE entry_ref IN ({placeholders})",
            tuple(entry_refs),
        )
        return {
            str(row["entry_ref"]): {
                "timeFlags": int(row["time_flags"] or 0),
                "fetchedAt": int(row["fetched_at"] or 0),
            }
            for row in rows
        }

    async def variants_block(
        self, entry_ref: str, *, current_html: str | None
    ) -> ContentVariantsBlock | None:
        """N032 block, or None when not triggered / nothing to offer.

        Honest labels only: 「上游当前」always; 「上次完整版本 (capturedAt)」
        only when the bounded long version is actually retained. Unknown
        stays unknown — lengths come from stored facts, never guesses.
        """
        await self._db.migrate()
        current = current_html or ""
        row = await self._db.fetch_one(
            "SELECT content_max_len FROM search_entries WHERE entry_ref = ?",
            (entry_ref,),
        )
        max_len = int(row["content_max_len"] or 0) if row is not None else 0
        if max_len <= 0 or len(current) >= max_len * _TRIGGER_RATIO:
            return None
        options = [
            ContentVariantOption(
                kind="current",
                label=_VARIANT_LABELS["current"],
                capturedAt=None,
                contentHtml=current or None,
                lengthChars=len(current),
            )
        ]
        variant = await self._db.fetch_one(
            "SELECT content_html, captured_at FROM entry_content_variants WHERE entry_ref = ?",
            (entry_ref,),
        )
        if variant is not None:
            options.append(
                ContentVariantOption(
                    kind="last_known_full",
                    label=_VARIANT_LABELS["last_known_full"],
                    capturedAt=str(variant["captured_at"]),
                    contentHtml=str(variant["content_html"]),
                    lengthChars=len(str(variant["content_html"])),
                )
            )
        return ContentVariantsBlock(
            triggered=True,
            currentLength=len(current),
            maxLength=max_len,
            variants=options,
        )


def credibility_codes(flags: int) -> str | None:
    """Bitmask → wire value (comma-joined codes); no anomaly → None."""
    codes = time_flag_codes(flags)
    return ",".join(codes) if codes else None
