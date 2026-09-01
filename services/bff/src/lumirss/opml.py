"""OPML support for the subscription center (0013 Gate 4).

OPML files are UNTRUSTED XML:

- uploads are size-bounded (route reads the body with a hard cap before
  parsing anything);
- parsing goes through defusedxml (DTDs / entity expansion forbidden —
  no billion-laughs, no external entities);
- only the subscription-relevant subset is extracted: category outline
  containers and feed outlines (xmlUrl). Everything else is ignored.

Import is MERGE-ONLY: existing subscriptions are reported as duplicates
and never touched; nothing is unsubscribed, renamed or overwritten. Each
new feed is subscribed exactly once (the control adapter's semantics);
per-feed failures are collected and reported honestly instead of failing
the whole import.
"""

from dataclasses import dataclass, field

import defusedxml.ElementTree as SafeET

from lumirss.adapters.freshrss import AdapterError
from lumirss.adapters.freshrss_control import FreshRSSControlAdapter, InvalidFeedUrl

MAX_OPML_BYTES = 2 * 1024 * 1024  # aligned with the feed-preview bound
MAX_OPML_FEEDS = 500
MAX_OPML_DEPTH = 8  # outline nesting cap (body > folder > feed is depth 2)

_CATEGORY_PREFIX = "user/-/label/"
# FreshRSS's default-category DB name (see freshrss_control): an OPML label
# equal to it means "default category" — subscribing already lands there.
_RESERVED_CATEGORY_LABEL = "Uncategorized"


class OpmlInvalid(AdapterError):
    """The file is not a well-formed OPML document."""


class OpmlTooLarge(AdapterError):
    """The uploaded OPML exceeds the size limit."""


class OpmlTooManyFeeds(AdapterError):
    """The OPML carries more feed outlines than the import limit allows."""


@dataclass
class OpmlEntry:
    """One feed outline (title may be empty; category None = uncategorized)."""

    title: str
    feed_url: str
    category_label: str | None = None


@dataclass
class ParsedOpml:
    entries: list[OpmlEntry] = field(default_factory=list)
    invalid_entries: int = 0  # outlines with an unusable xmlUrl
    # the same feed URL repeated inside the file (first occurrence wins):
    file_duplicates: list[OpmlEntry] = field(default_factory=list)

    @property
    def duplicate_count(self) -> int:
        return len(self.file_duplicates)


def _is_usable_feed_url(url: str) -> bool:
    """Same rule as the control adapter's subscribe path (http(s), bounded)."""
    try:
        FreshRSSControlAdapter._validate_feed_url(url)
    except InvalidFeedUrl:
        return False
    return True


def parse_opml(data: bytes) -> ParsedOpml:
    """Safely extract feed outlines + category labels from OPML bytes.

    Structure: <opml><body><outline text="Category"><outline text="Feed"
    xmlUrl="…"/></outline>…</body></opml>. Containers without a label are
    transparent (their feeds inherit the outer label); feeds directly under
    <body> are uncategorized. Repeated feed URLs keep the first occurrence.
    """
    if len(data) > MAX_OPML_BYTES:
        raise OpmlTooLarge("OPML file exceeds the 2 MiB limit.")
    try:
        root = SafeET.fromstring(data)
    except Exception as exc:
        raise OpmlInvalid("The file is not well-formed XML.") from exc
    if root.tag != "opml":
        raise OpmlInvalid("The file is not an OPML document (missing <opml> root).")
    body = root.find("body")
    if body is None:
        raise OpmlInvalid("OPML document has no <body>.")

    parsed = ParsedOpml()
    feed_outlines = 0

    def walk(element, category: str | None, depth: int) -> None:
        nonlocal feed_outlines
        if depth > MAX_OPML_DEPTH:
            raise OpmlInvalid("OPML outline nesting is too deep.")
        for outline in element.findall("outline"):
            xml_url = outline.get("xmlUrl")
            if xml_url is not None:
                feed_outlines += 1
                if feed_outlines > MAX_OPML_FEEDS:
                    raise OpmlTooManyFeeds(
                        "OPML carries more than 500 feed outlines."
                    )
                if not _is_usable_feed_url(xml_url):
                    parsed.invalid_entries += 1
                    continue
                title = (outline.get("text") or outline.get("title") or "").strip()
                parsed.entries.append(
                    OpmlEntry(title=title, feed_url=xml_url, category_label=category)
                )
            else:
                label = (outline.get("text") or outline.get("title") or "").strip()
                # Nested containers flatten onto the OUTERMOST real label.
                walk(outline, category if category is not None else (label or None), depth + 1)

    walk(body, None, 0)

    # Deduplicate by feed URL (first occurrence wins).
    seen: set[str] = set()
    deduped: list[OpmlEntry] = []
    for entry in parsed.entries:
        if entry.feed_url in seen:
            parsed.file_duplicates.append(entry)
        else:
            seen.add(entry.feed_url)
            deduped.append(entry)
    parsed.entries = deduped
    return parsed


def _failure_type(exc: AdapterError) -> str:
    """Stable short code for a per-feed import failure."""
    from lumirss.adapters.freshrss import (
        AuthenticationError,
        UpstreamConnectionError,
    )
    from lumirss.adapters.freshrss_control import FeedRejectedError

    if isinstance(exc, FeedRejectedError):
        return "feed_rejected"
    if isinstance(exc, UpstreamConnectionError):
        return "connection_error"
    if isinstance(exc, AuthenticationError):
        return "authentication_error"
    return "upstream_error"


class OpmlService:
    """Preview (non-mutating) and merge-import over the control adapter."""

    def __init__(self, control: FreshRSSControlAdapter) -> None:
        self._control = control

    async def preview(self, data: bytes) -> dict[str, object]:
        """Count what an import WOULD do — strictly read-only."""
        parsed = parse_opml(data)
        existing = {
            subscription.feed_url
            for subscription in await self._control.list_subscriptions()
        }
        new_feeds = 0
        duplicates = parsed.duplicate_count
        for entry in parsed.entries:
            if entry.feed_url in existing:
                duplicates += 1
            else:
                new_feeds += 1

        category_counts: dict[str, int] = {}
        for entry in parsed.entries:
            if entry.category_label is not None:
                category_counts[entry.category_label] = (
                    category_counts.get(entry.category_label, 0) + 1
                )
        return {
            "totalFeeds": len(parsed.entries),
            "newFeeds": new_feeds,
            "duplicates": duplicates,
            "invalidEntries": parsed.invalid_entries,
            "categories": [
                {"label": label, "feedCount": count}
                for label, count in sorted(category_counts.items())
            ],
        }

    async def import_opml(self, data: bytes) -> dict[str, object]:
        """Merge-import: subscribe each NEW feed once, then categorize it.

        Merge semantics — existing subscriptions are reported as duplicates
        and never modified. Category assignment happens per feed after the
        subscribe is server-confirmed: existing categories are reused, a
        missing one is created by the move itself (the only FreshRSS
        create-category channel, 0013 Gate 3). A failed category move never
        undoes the subscription — the feed stays in the default category and
        the result reports categoryApplied=false.
        """
        parsed = parse_opml(data)
        subscriptions = await self._control.list_subscriptions()
        existing_urls = {subscription.feed_url for subscription in subscriptions}
        label_to_id = {
            category.label: category.id
            for category in await self._control.list_categories()
        }

        added: list[dict[str, object]] = []
        duplicates: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []
        categories_created: list[str] = []

        def _duplicate(entry: OpmlEntry) -> dict[str, str]:
            return {"feedUrl": entry.feed_url, "title": entry.title or entry.feed_url}

        # in-file repeats share the fate of their first occurrence
        duplicates.extend(_duplicate(entry) for entry in parsed.file_duplicates)

        for entry in parsed.entries:
            display_title = entry.title or entry.feed_url
            if entry.feed_url in existing_urls:
                duplicates.append(_duplicate(entry))
                continue

            try:
                subscription = await self._control.subscribe(
                    entry.feed_url, title=entry.title or None
                )
            except AdapterError as exc:
                failed.append(
                    {
                        "feedUrl": entry.feed_url,
                        "title": display_title,
                        "error": _failure_type(exc),
                    }
                )
                continue
            existing_urls.add(entry.feed_url)

            label = (entry.category_label or "").strip()
            category_applied = False
            if label and label != _RESERVED_CATEGORY_LABEL:
                try:
                    target_id = label_to_id.get(label)
                    if target_id is None:
                        await self._control.move_to_new_category(
                            subscription.stream_id, label
                        )
                        # greader contract: the created category's id is
                        # derived from its label (verified in Gate 1/3).
                        target_id = f"{_CATEGORY_PREFIX}{label}"
                        categories_created.append(label)
                    else:
                        await self._control.move_category(
                            subscription.stream_id, target_id
                        )
                    label_to_id[label] = target_id
                    category_applied = True
                except AdapterError:
                    category_applied = False  # stays in the default category

            added.append(
                {
                    "feedUrl": entry.feed_url,
                    "title": subscription.title,
                    "categoryLabel": label or None,
                    "categoryApplied": category_applied,
                }
            )

        return {
            "added": added,
            "duplicates": duplicates,
            "failed": failed,
            "categoriesCreated": categories_created,
        }
