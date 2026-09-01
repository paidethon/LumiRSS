"""Feed preview — 0013 Gate 2 direct RSS/Atom preview (NO side effects).

``POST /api/v1/feed-preview`` fetches a user-supplied feed URL through a
minimal, reusable safe-fetch boundary and parses it OFFLINE with
feedparser (bytes in — the parser never does its own networking):

    safe fetch → bounded bytes → parse RSS/Atom

Safe-fetch boundary (BFF actively dials a user URL, so it must defend
itself):

- http/https schemes only, absolute URLs, no embedded credentials;
- timeout on every request;
- bounded response body (Content-Length fast-path + streamed read cap);
- bounded redirects, and EVERY hop is re-validated like the first URL;
- DNS resolution is checked before dialing: every resolved address
  (IPv4 + IPv6) must be public — localhost/private/link-local/reserved/
  multicast/unspecified ranges, IPv4-mapped IPv6 and NAT64 prefixes are
  all rejected.

``preview`` is strictly non-mutating: it fetches the URL, parses the
document and READS the FreshRSS subscription list to compute
``alreadySubscribed``. It never calls any FreshRSS mutation endpoint —
subscribing is ``POST /api/v1/subscriptions`` (Gate 1).
"""

import asyncio
import ipaddress
import socket
import urllib.parse
from dataclasses import dataclass

import feedparser
import httpx

from lumirss.adapters.freshrss import AdapterError, html_to_text
from lumirss.adapters.freshrss_control import InvalidFeedUrl

# Re-exported so main.py's error table can map it next to the preview errors.
__all__ = [
    "AdapterError",
    "FeedFetchError",
    "FeedPreview",
    "FeedPreviewService",
    "FeedTooLarge",
    "FetchedDocument",
    "InvalidFeedUrl",
    "NotAFeedError",
    "UnsafeFeedUrl",
    "parse_feed_document",
    "safe_fetch",
    "validate_feed_url",
]


class UnsafeFeedUrl(AdapterError):
    """The URL (or a redirect target) resolves to a non-public address."""


class FeedFetchError(AdapterError):
    """The feed URL could not be fetched (network, timeout or HTTP status)."""


class FeedTooLarge(AdapterError):
    """The feed document exceeds the bounded response size."""


class NotAFeedError(AdapterError):
    """The fetched document is not a parseable RSS/Atom feed."""


_MAX_URL_LENGTH = 2048
MAX_FEED_BODY_BYTES = 2 * 1024 * 1024  # 2 MiB: feeds are XML metadata, not media
_MAX_REDIRECTS = 5
_CHUNK = 64 * 1024
_MAX_TITLE_LENGTH = 300
_MAX_DESCRIPTION_LENGTH = 300

# Rejected address space: anything the BFF must never dial. is_private
# covers RFC1918/loopback-ish ranges but the explicit flags (and the NAT64
# / carrier-grade checks below) make the boundary independent of the exact
# stdlib constants per Python version.
_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")
_CGNAT_PREFIX = ipaddress.ip_network("100.64.0.0/10")

_HEADERS = {"User-Agent": "LumiRSS/0.1 (+self-hosted feed preview)"}


@dataclass(frozen=True)
class FeedPreview:
    """Reliable preview metadata only — no entries, no summaries."""

    title: str
    feed_url: str
    site_url: str | None
    description: str | None
    format: str  # "rss" | "atom"
    already_subscribed: bool


@dataclass(frozen=True)
class FetchedDocument:
    """Result of one bounded safe fetch (body + provenance + content type)."""

    body: bytes
    final_url: str
    content_type: str | None


async def _default_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


def validate_feed_url(url: str) -> urllib.parse.SplitResult:
    """Structural validation shared by the first URL and every redirect hop.

    Raises InvalidFeedUrl for malformed input and UnsafeFeedUrl for URLs
    carrying embedded credentials (both before any network activity).
    """
    if len(url) > _MAX_URL_LENGTH:
        raise InvalidFeedUrl("Feed URL is too long.")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise InvalidFeedUrl("Feed URL must be an absolute http(s) URL.")
    if parts.username is not None or parts.password is not None:
        raise UnsafeFeedUrl("Feed URL must not contain credentials.")
    try:
        parts.port  # noqa: B018 — accessing .port validates the range
    except ValueError as exc:
        raise InvalidFeedUrl("Feed URL has an invalid port.") from exc
    return parts


def ensure_public_address(address: str) -> None:
    """Reject every address the BFF must not dial (IPv4 + IPv6)."""
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped  # ::ffff:10.0.0.1 → 10.0.0.1
        elif ip in _NAT64_PREFIX:
            raise UnsafeFeedUrl("Feed URL resolves to a non-public address.")
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or ip in _CGNAT_PREFIX
    ):
        raise UnsafeFeedUrl("Feed URL resolves to a non-public address.")


def parse_feed_document(raw: bytes) -> tuple[str, str | None, str | None, str]:
    """Parse bounded feed bytes OFFLINE (feedparser never networks here).

    Returns (title, siteUrl, description, format); raises NotAFeedError
    when the document is not a feed with a usable title. Only reliable
    metadata is extracted — no entries.
    """
    parsed = feedparser.parse(raw)
    version = parsed.get("version") or ""
    if version.startswith("rss"):
        feed_format = "rss"
    elif version.startswith("atom"):
        feed_format = "atom"
    else:
        raise NotAFeedError("This URL did not return an RSS or Atom feed.")

    feed = parsed.feed
    raw_title = feed.get("title")
    title = raw_title.strip() if isinstance(raw_title, str) else ""
    if not title:
        raise NotAFeedError("This feed has no title.")

    site_url = _safe_site_url(feed.get("link"))
    description = _plain_text(feed.get("description") or feed.get("subtitle"))
    return title[:_MAX_TITLE_LENGTH], site_url, description, feed_format


def _safe_site_url(link: object) -> str | None:
    """The feed's site link is untrusted: keep absolute http(s) URLs only."""
    if not isinstance(link, str) or not link.strip():
        return None
    parts = urllib.parse.urlsplit(link.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    return link.strip()[:_MAX_URL_LENGTH]


def _plain_text(value: object) -> str | None:
    """Feed descriptions may carry HTML — reduce to plain text, bounded."""
    if not isinstance(value, str):
        return None
    try:
        text = html_to_text(value)
    except AdapterError:
        text = value  # extractor gave up: fall back to the raw string
    text = " ".join(text.split())
    if not text:
        return None
    return text[:_MAX_DESCRIPTION_LENGTH]


class FeedPreviewService:
    """Safe-fetch + offline-parse preview over the shared HTTP client.

    ``control`` (FreshRSSControlAdapter) is used read-only, for
    ``alreadySubscribed``; ``resolver`` is injectable so tests never hit
    real DNS.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        control,
        *,
        resolver=_default_resolver,
    ) -> None:
        self._client = client
        self._control = control
        self._resolver = resolver

    async def preview(self, feed_url: str) -> FeedPreview:
        validate_feed_url(feed_url)
        document = await safe_fetch(self._client, feed_url, resolver=self._resolver)
        title, site_url, description, feed_format = parse_feed_document(
            document.body
        )
        existing = await self._control.list_subscriptions()
        already_subscribed = any(s.feed_url == feed_url for s in existing)
        return FeedPreview(
            title=title,
            feed_url=feed_url,
            site_url=site_url,
            description=description,
            format=feed_format,
            already_subscribed=already_subscribed,
        )

async def safe_fetch(
    client: httpx.AsyncClient,
    url: str,
    *,
    resolver=_default_resolver,
    max_redirects: int = _MAX_REDIRECTS,
) -> "FetchedDocument":
    """Bounded, redirect-aware fetch with per-hop re-validation.

    Shared by feed preview and source discovery: every hop (including
    redirect targets) passes the same URL/DNS/IP validation as the first
    URL. The result carries the FINAL URL (so callers can resolve relative
    links against where the document actually came from) and the final
    content-type header.
    """
    current = url
    for _hop in range(max_redirects + 1):
        await _require_dialable(resolver, validate_feed_url(current))
        response = await _send(client, current)
        try:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise FeedFetchError(
                        "Feed URL redirected without a target location."
                    )
                current = urllib.parse.urljoin(current, location)
                continue
            if response.status_code != 200:
                raise FeedFetchError(
                    f"The feed URL answered HTTP {response.status_code}."
                )
            return FetchedDocument(
                body=await _bounded_body(response),
                final_url=current,
                content_type=response.headers.get("content-type"),
            )
        finally:
            await response.aclose()
    raise FeedFetchError("Feed URL redirected too many times.")


async def _send(client: httpx.AsyncClient, url: str) -> httpx.Response:
    request = client.build_request("GET", url, headers=_HEADERS)
    try:
        # follow_redirects stays OFF: redirects are handled manually so
        # every hop goes through the same validation as the first URL.
        return await client.send(request, stream=True)
    except httpx.HTTPError as exc:
        raise FeedFetchError("The feed URL could not be reached.") from exc


async def _bounded_body(response: httpx.Response) -> bytes:
    if (length := response.headers.get("content-length")) is not None:
        try:
            if int(length) > MAX_FEED_BODY_BYTES:
                raise FeedTooLarge("The feed document is too large.")
        except ValueError:
            pass  # malformed Content-Length: the streamed cap decides
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes(_CHUNK):
        size += len(chunk)
        if size > MAX_FEED_BODY_BYTES:
            raise FeedTooLarge("The feed document is too large.")
        chunks.append(chunk)
    return b"".join(chunks)


async def _require_dialable(resolver, parts: urllib.parse.SplitResult) -> None:
    host = parts.hostname
    if not host:
        raise InvalidFeedUrl("Feed URL must name a host.")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        addresses = await resolver(host, port)
    except (socket.gaierror, OSError) as exc:
        raise FeedFetchError(f"The feed host '{host}' could not be resolved.") from exc
    for address in addresses:
        ensure_public_address(address)
