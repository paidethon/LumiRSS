"""Entry intake helpers — bounded metadata computed at projection time.

Pure functions shared by the projection write path (search_writer):

- content hashing (N031 revision detection: SAME id, changed hash);
- structural token counts + first-differing-block excerpts (N031) —
  computed from the HTML WITHOUT storing any full content copy, so the
  projection stays non-authoritative and rebuildable;
- published-time credibility classification (N034) as a small bitmask.

Bounded by design: every text output is truncated (titles 500, excerpts
200, summaries are fixed-key JSON); nothing here ever persists article
bodies.
"""

import hashlib
import json
from datetime import UTC, datetime
from html.parser import HTMLParser

# N031: revision summary bounds. The revision row must stay metadata-sized
# (the test suite asserts no full-content row), so every text field is
# individually capped.
_EXCERPT_CHARS = 200
_TITLE_CHARS = 500
_SUMMARY_MAX_JSON_CHARS = 4000

# N034: classification codes and the bitmask they map to.
TIME_FLAG_MISSING = 1
TIME_FLAG_NO_TIMEZONE = 2
TIME_FLAG_FUTURE = 4
TIME_FLAG_TOO_OLD = 8

_TIME_FLAG_CODES: list[tuple[int, str]] = [
    (TIME_FLAG_MISSING, "missing"),
    (TIME_FLAG_NO_TIMEZONE, "no_timezone"),
    (TIME_FLAG_FUTURE, "future"),
    (TIME_FLAG_TOO_OLD, "too_old"),
]

_FUTURE_TOLERANCE_SECONDS = 24 * 3600  # > now + 1d counts as "future"
_TOO_OLD_FLOOR = "2000-01-01T00:00:00Z"


# -- HTML structural extraction (bounded, stdlib only) ----------------------


class _StructureParser(HTMLParser):
    """Counts structural tokens and collects block text (no content kept
    beyond the current block)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings = 0
        self.paragraphs = 0
        self.links = 0
        self._parts: list[str] = []
        self._skipping = 0
        self.blocks: list[str] = []

    def handle_starttag(self, tag, attrs):  # noqa: ARG002
        if self._skipping:
            self._skipping += 0 if tag in ("br", "hr", "img", "meta", "link", "input") else 1
            return
        if tag in ("script", "style"):
            self._skipping = 1
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.headings += 1
        elif tag == "p":
            self.paragraphs += 1
        elif tag == "a":
            self.links += 1
        if tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "div", "br", "tr"):
            self._flush_block()

    def handle_endtag(self, tag):
        if self._skipping:
            if tag not in ("br", "hr", "img", "meta", "link", "input"):
                self._skipping = max(0, self._skipping - 1)
            return
        if tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "div", "tr"):
            self._flush_block()

    def handle_data(self, data):
        if not self._skipping:
            self._parts.append(data)

    def _flush_block(self) -> None:
        text = " ".join("".join(self._parts).split())
        self._parts = []
        if text:
            self.blocks.append(text)


def _parse_structure(html: str) -> _StructureParser:
    parser = _StructureParser()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:  # noqa: BLE001 — hostile/malformed HTML never blocks ingest
        pass
    return parser


def content_hash(content: str) -> str:
    """Stable hash of the delivered content (N031 change detection)."""
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def structural_counts(html: str) -> dict[str, int]:
    """Headings / paragraphs / links token counts of one version."""
    parser = _parse_structure(html)
    return {
        "headings": parser.headings,
        "paragraphs": parser.paragraphs,
        "links": parser.links,
    }


def _first_differing_excerpts(prev_blocks: list[str], new_blocks: list[str]) -> tuple[str, str]:
    """First differing block, ≤200 chars per side (empty when equal/absent)."""
    for index in range(max(len(prev_blocks), len(new_blocks))):
        prev_text = prev_blocks[index] if index < len(prev_blocks) else ""
        new_text = new_blocks[index] if index < len(new_blocks) else ""
        if prev_text != new_text:
            return prev_text[:_EXCERPT_CHARS], new_text[:_EXCERPT_CHARS]
    return "", ""


def revision_diff_summary(
    prev_html: str,
    new_html: str,
    *,
    basis: str,
) -> dict:
    """Structural diff summary for one revision (N031).

    Fixed-key JSON-serializable dict; ``basis`` is honest about what the
    diff compares: "retained_variant" (the bounded long version kept by
    N032) or "hash_only" (nothing retained — counts report the NEW version
    only and excerpts stay empty; no content is fabricated).
    """
    prev_parser = _parse_structure(prev_html)
    new_parser = _parse_structure(new_html)
    if basis == "retained_variant":
        excerpt_prev, excerpt_new = _first_differing_excerpts(
            prev_parser.blocks, new_parser.blocks
        )
    else:
        excerpt_prev, excerpt_new = "", ""
    summary = {
        "basis": basis,
        "headingsChanged": new_parser.headings - prev_parser.headings,
        "paragraphsChanged": new_parser.paragraphs - prev_parser.paragraphs,
        "linksChanged": new_parser.links - prev_parser.links,
        "excerptPrev": excerpt_prev,
        "excerptNew": excerpt_new,
    }
    return _bound_summary(summary)


def _bound_summary(summary: dict) -> dict:
    """Keep the serialized summary metadata-sized (defense in depth)."""
    encoded = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) <= _SUMMARY_MAX_JSON_CHARS:
        return summary
    trimmed = dict(summary)
    trimmed["excerptPrev"] = summary["excerptPrev"][:_EXCERPT_CHARS]
    trimmed["excerptNew"] = summary["excerptNew"][:_EXCERPT_CHARS]
    return trimmed


def bound_title(title: str) -> str:
    return (title or "")[:_TITLE_CHARS]


def decode_summary(raw: str | None) -> dict:
    """Parse a stored summary JSON; corrupt rows degrade to an honest
    empty dict instead of failing the read path."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


# -- published-time credibility (N034) --------------------------------------


def classify_published_at(published_at: str | None, *, now_epoch: float) -> int:
    """Bitmask of published-time anomalies (0 = no anomaly detected).

    - missing: empty/absent value;
    - no_timezone: parseable but carries no UTC offset (naive) — cannot
      occur through the FreshRSS epoch normalization, kept for honesty and
      direct ingestion paths;
    - future: more than 1 day ahead of the ingest moment;
    - too_old: before 2000-01-01.
    """
    flags = 0
    if published_at is None or not published_at.strip():
        return TIME_FLAG_MISSING
    text = published_at.strip()
    iso_text = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(iso_text)
    except ValueError:
        # Unparseable: the raw value stays visible in the UI; do not
        # fabricate a specific anomaly class for it.
        return flags
    if parsed.tzinfo is None:
        flags |= TIME_FLAG_NO_TIMEZONE
        parsed = parsed.replace(tzinfo=UTC)
    if parsed.timestamp() > now_epoch + _FUTURE_TOLERANCE_SECONDS:
        flags |= TIME_FLAG_FUTURE
    try:
        if parsed.timestamp() < datetime.fromisoformat(
            _TOO_OLD_FLOOR[:-1] + "+00:00"
        ).timestamp():
            flags |= TIME_FLAG_TOO_OLD
    except ValueError:  # pragma: no cover — constant floor always parses
        pass
    return flags


def time_flag_codes(flags: int) -> list[str]:
    """Bitmask → stable code list (API wire format; empty = credible)."""
    return [code for mask, code in _TIME_FLAG_CODES if flags & mask]
