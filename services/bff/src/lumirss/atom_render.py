"""Shared RFC 4287 Atom rendering (phase2 recovery, IMPL-BE-2).

One renderer for BOTH Lumi-generated feeds (API-source conversion and
the mail bridge) so the two legs cannot drift into non-conformance
again (audit P0-05d / P0-06i). Structural guarantees:

- feed: id / title / updated (never empty) / link rel=self (absolute
  IRI) / author;
- entry: id / title / updated (REQUIRED — content-derived when the
  source provides a valid timestamp, else the stable feed fallback,
  never blank) / author (per-entry when known, inherited feed author
  otherwise) / content (type="html", stdlib-escaped);
- published emitted only when it parses as RFC 3339.

Timestamps: every input passes through :func:`rfc3339` (parses RFC 3339
date-times, normalizes to a canonical UTC string; ``None`` when
invalid). Feed ``updated`` is derived by the callers via
:func:`newest_rfc3339` — newest entry timestamp clamped monotonic
against the persisted prior value — so identical content produces a
byte-identical feed (stable ETags, reliable 304s) and ``updated`` never
moves backwards.
"""

import xml.sax.saxutils as _xml
from dataclasses import dataclass
from datetime import UTC, datetime


def rfc3339(value: object) -> str | None:
    """Normalize a timestamp-ish value to canonical RFC 3339 UTC, or None.

    Accepts ``...Z`` / explicit offsets / naive (assumed UTC). Invalid or
    missing values yield None — callers must treat None as "no usable
    timestamp" and fall back, never emit an empty <updated>.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


def newest_rfc3339(values: list[str | None]) -> str | None:
    """Newest valid timestamp among the candidates (None when all invalid).

    Candidates are already normalized by :func:`rfc3339`, so lexicographic
    comparison is chronological (single canonical format)."""
    valid = [value for value in values if value]
    return max(valid) if valid else None


@dataclass(frozen=True)
class AtomEntry:
    """One RFC 4287 entry; ``updated`` is REQUIRED and pre-resolved."""

    entry_id: str
    title: str
    updated: str
    link: str | None = None
    author: str | None = None
    content_html: str = ""
    published: str | None = None


def _esc_attr(text: str) -> str:
    return _xml.escape(text, {'"': "&quot;"})


def render_feed(
    *,
    feed_id: str,
    title: str,
    updated: str,
    self_href: str,
    entries: list[AtomEntry],
    feed_author: str | None = None,
) -> str:
    """Render the complete Atom document with stdlib escaping only."""
    esc = _xml.escape
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <title>{esc(title)}</title>",
        f"  <id>{esc(feed_id)}</id>",
        f"  <updated>{esc(updated)}</updated>",
        f'  <link rel="self" href="{_esc_attr(self_href)}"/>',
    ]
    if feed_author:
        lines.append("  <author>")
        lines.append(f"    <name>{esc(feed_author)}</name>")
        lines.append("  </author>")
    for entry in entries:
        entry_updated = rfc3339(entry.updated) or updated
        lines.append("  <entry>")
        lines.append(f"    <id>{esc(entry.entry_id)}</id>")
        lines.append(f"    <title>{esc(entry.title)}</title>")
        if entry.link:
            lines.append(f'    <link href="{_esc_attr(entry.link)}"/>')
        if entry.published:
            lines.append(f"    <published>{esc(entry.published)}</published>")
        lines.append(f"    <updated>{esc(entry_updated)}</updated>")
        if entry.author:
            lines.append("    <author>")
            lines.append(f"      <name>{esc(entry.author)}</name>")
            lines.append("    </author>")
        lines.append(
            f'    <content type="html">{esc(entry.content_html)}</content>'
        )
        lines.append("  </entry>")
    lines.append("</feed>")
    return "\n".join(lines) + "\n"
