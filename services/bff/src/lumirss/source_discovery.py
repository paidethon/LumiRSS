"""Source discovery — 0014: website → RSS/Atom candidate discovery.

``POST /api/v1/source-discovery`` takes an ordinary public website URL and
returns usable feed candidates WITHOUT subscribing, scraping or crawling:

    1. safe-fetch the page (same boundary as feed preview: http/https
       only, public destinations only, bounded body, bounded redirects);
    2. if the document IS a feed (someone pasted a feed URL), return it
       as a single candidate;
    3. otherwise, for HTML pages, extract explicit ``<link
       rel="alternate">`` RSS/Atom declarations (relative hrefs are
       resolved against the FINAL fetch URL, duplicates removed);
    4. only when no declaration exists, probe a small bounded set of
       common feed endpoints (/feed, /rss, /rss.xml, /atom.xml,
       /feed.xml) in order and keep the FIRST one that parses as a feed.

This is feed discovery, not generic scraping: no recursion, no crawling,
no DOM/card extraction. Declared candidates are NOT fetched here (they are
validated on preview); only probed endpoints are fetched, bounded to the
common-endpoint list. The service never touches FreshRSS at all — it holds
no control adapter reference, so discovery is read-only by construction.
"""

from dataclasses import dataclass
from html.parser import HTMLParser
import urllib.parse

import httpx

from lumirss.adapters.freshrss import AdapterError
from lumirss.adapters.freshrss_control import InvalidFeedUrl
from lumirss.feed_preview import (
    FeedFetchError,
    FeedTooLarge,
    NotAFeedError,
    UnsafeFeedUrl,
    _default_resolver,
    parse_feed_document,
    safe_fetch,
    validate_feed_url,
)

__all__ = [
    "COMMON_FEED_PATHS",
    "DiscoveryCandidate",
    "InvalidSourceUrl",
    "NoFeedDiscovered",
    "SourceDiscoveryService",
    "extract_declared_feed_links",
]

_MAX_DECLARED_CANDIDATES = 20

# Bounded common-endpoint probing: first parse success wins (≤5 fetches).
COMMON_FEED_PATHS = ("/feed", "/rss", "/rss.xml", "/atom.xml", "/feed.xml")

# Feeds must be declared as alternates with an RSS/Atom type. When the
# type attribute is missing entirely, only obviously feed-ish hrefs count.
_FEED_TYPE_MARKERS = ("rss", "atom")
_FEED_HREF_SUFFIXES = (".xml", ".rss", ".atom", ".feed")


class InvalidSourceUrl(AdapterError):
    """The website URL is malformed (not an absolute http(s) URL)."""


class NoFeedDiscovered(AdapterError):
    """The website declared no feeds and no common endpoint worked."""


@dataclass(frozen=True)
class DiscoveryCandidate:
    """One usable feed candidate (Lumi DTO — never raw upstream data).

    ``source`` is "declared" (explicit rel=alternate link, not fetched:
    format unknown until preview) or "probed" (a common endpoint that
    already parsed as a feed, so title/format are known).
    """

    feed_url: str
    title: str | None
    source: str  # "declared" | "probed"
    format: str | None  # "rss" | "atom" | None


class _FeedLinkParser(HTMLParser):
    """Extract <link rel~=alternate> elements; never fetches anything."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []

    def _collect(self, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.lower(): (value or "") for name, value in attrs}
        if _rel_has_alternate(attributes.get("rel", "")):
            self.links.append(attributes)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "link":
            self._collect(attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "link":
            self._collect(attrs)


def _rel_has_alternate(rel: str) -> bool:
    return "alternate" in [token.lower() for token in rel.split()]


def _is_feedish_link(attributes: dict[str, str]) -> bool:
    declared_type = attributes.get("type", "")
    if declared_type:
        return any(marker in declared_type.lower() for marker in _FEED_TYPE_MARKERS)
    href_path = urllib.parse.urlsplit(attributes.get("href", "")).path.lower()
    return href_path.endswith(_FEED_HREF_SUFFIXES)


def extract_declared_feed_links(
    html: bytes, final_url: str
) -> list[DiscoveryCandidate]:
    """Declared rel=alternate feed links, resolved and deduplicated.

    Relative hrefs resolve against ``final_url`` (the page's real location
    after redirects). Malformed hrefs and non-http(s) targets are skipped;
    duplicates (exact URL, fragment-insensitive) collapse to the first.
    """
    parser = _FeedLinkParser()
    try:
        parser.feed(html.decode("utf-8", errors="replace"))
    except Exception:  # pragma: no cover - parser gives up: no candidates
        return []
    candidates: list[DiscoveryCandidate] = []
    seen: set[str] = set()
    for attributes in parser.links:
        href = attributes.get("href", "").strip()
        if not href or not _is_feedish_link(attributes):
            continue
        resolved = urllib.parse.urljoin(final_url, href)
        try:
            parts = validate_feed_url(resolved)
        except (InvalidFeedUrl, UnsafeFeedUrl):
            continue  # malformed / credentialed declaration: skip
        normalized = urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, parts.path, parts.query, "")
        )
        if normalized in seen:
            continue
        seen.add(normalized)
        title = attributes.get("title", "").strip() or None
        candidates.append(
            DiscoveryCandidate(
                feed_url=normalized,
                title=title,
                source="declared",
                format=None,
            )
        )
        if len(candidates) >= _MAX_DECLARED_CANDIDATES:
            break
    return candidates


def _looks_like_html(content_type: str | None) -> bool:
    """Non-HTML media (JSON APIs, images…) gets no link extraction."""
    if content_type is None:
        return True  # lenient: misconfigured servers often omit the header
    return "html" in content_type.lower()


class SourceDiscoveryService:
    """Website → feed candidates, over the shared HTTP client.

    Read-only by construction: the service holds no FreshRSS reference at
    all, so discovery can never mutate subscription state.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        resolver=_default_resolver,
        common_feed_paths: tuple[str, ...] = COMMON_FEED_PATHS,
    ) -> None:
        self._client = client
        self._resolver = resolver
        self._common_feed_paths = common_feed_paths

    async def discover(self, url: str) -> list[DiscoveryCandidate]:
        """Discover feed candidates for a website URL.

        Raises InvalidSourceUrl / UnsafeFeedUrl / FeedFetchError /
        FeedTooLarge / NoFeedDiscovered — all mapped to stable API errors
        in main.py.
        """
        try:
            validate_feed_url(url)
        except InvalidFeedUrl as exc:
            raise InvalidSourceUrl(
                "Source URL must be an absolute http(s) URL."
            ) from exc
        document = await safe_fetch(self._client, url, resolver=self._resolver)

        # The URL may already be a feed (paste-into-website-box case):
        # return it directly, no link extraction, no probing.
        try:
            title, _site, _description, feed_format = parse_feed_document(
                document.body
            )
        except NotAFeedError:
            pass
        else:
            return [
                DiscoveryCandidate(
                    feed_url=document.final_url,
                    title=title,
                    source="declared",
                    format=feed_format,
                )
            ]

        candidates: list[DiscoveryCandidate] = []
        if _looks_like_html(document.content_type):
            candidates = extract_declared_feed_links(
                document.body, document.final_url
            )

        if not candidates:
            probed = await self._probe_common_endpoints(document.final_url)
            if probed is not None:
                candidates = [probed]

        if not candidates:
            raise NoFeedDiscovered(
                "No RSS or Atom feed was discovered for this website."
            )
        return candidates

    async def _probe_common_endpoints(
        self, final_url: str
    ) -> DiscoveryCandidate | None:
        """Probe common feed endpoints; first parseable feed wins.

        Failures (404, non-feed, unreachable) simply move to the next
        path — probing is best-effort, never an error by itself.
        """
        base = urllib.parse.urlsplit(final_url)
        origin = urllib.parse.urlunsplit((base.scheme, base.netloc, "/", "", ""))
        for path in self._common_feed_paths:
            probe_url = urllib.parse.urljoin(origin, path)
            try:
                document = await safe_fetch(
                    self._client, probe_url, resolver=self._resolver
                )
                title, _site, _description, feed_format = parse_feed_document(
                    document.body
                )
            except (
                FeedFetchError,
                FeedTooLarge,
                NotAFeedError,
                UnsafeFeedUrl,
            ):
                continue
            return DiscoveryCandidate(
                feed_url=document.final_url,
                title=title,
                source="probed",
                format=feed_format,
            )
        return None
