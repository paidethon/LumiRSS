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

    Accepts ``...Z`` / explicit offsets / naive (assumed UTC) ISO strings,
    plus the two other shapes API sources commonly declare (FIX-157):
    numeric epoch seconds / milliseconds, and RFC 2822 date strings.
    Invalid or missing values yield None — callers must treat None as
    "no usable timestamp" and fall back, never emit an empty <updated>.
    """
    if isinstance(value, bool):  # bool 是 int 子类——绝不当 epoch
        return None
    if isinstance(value, (int, float)):
        return _epoch_to_rfc3339(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = _parse_rfc2822(text)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


# 数字 epoch 的可信量级（FIX-157）：低于 1e9「秒」是 1970s 噪声值，
# [1e12, 1e14) 是毫秒形态；两者之外不猜（宁可 None 退回稳定锚点）。
_EPOCH_SECONDS_MIN = 10**9
_EPOCH_SECONDS_MAX = 10**11
_EPOCH_MILLIS_MIN = 10**12
_EPOCH_MILLIS_MAX = 10**14


def _epoch_to_rfc3339(value: int | float) -> str | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if _EPOCH_MILLIS_MIN <= seconds < _EPOCH_MILLIS_MAX:
        seconds /= 1000.0
    elif not (_EPOCH_SECONDS_MIN <= seconds < _EPOCH_SECONDS_MAX):
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=UTC).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return None


def _parse_rfc2822(text: str):
    """RFC 2822（邮件/传统 API 的日期形态）→ datetime；不可解析返回 None。"""
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        return None


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
