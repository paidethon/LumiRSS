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
from lumirss.config import LumiSettings
from lumirss.http_fetch import follow_redirects

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
    "read_bounded_body",
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
    # N033：有界响应体的编码检查（声明/检测/乱码风险 + 掩码样本）。
    encoding_info: dict | None = None


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


def hostname_allowlisted(hostname: str | None) -> bool:
    """True when the operator explicitly vouched for this hostname to be
    dialable even though it resolves into a private network (deployment-
    internal sources such as an in-network RSSHub or an E2E fixture
    server). Exact, case-insensitive hostname match from the
    comma-separated LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS env; empty by
    default. The allow-list only skips the public-address REJECTION —
    the fetch still resolves, validates every address, and dials the
    pinned IP, so rebinding-class tricks stay dead."""
    if not hostname:
        return False
    configured = LumiSettings().LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS
    wanted = hostname.strip().casefold()
    return any(
        wanted == entry.strip().casefold()
        for entry in configured.split(",")
        if entry.strip()
    )


def parse_feed_document(
    raw: bytes,
    content_type: str | None = None,
    *,
    encoding_override: str | None = None,
) -> tuple[str, str | None, str | None, str]:
    """Parse bounded feed bytes OFFLINE (feedparser never networks here).

    Returns (title, siteUrl, description, format); raises NotAFeedError
    when the document is not a feed with a usable title. Only reliable
    metadata is extracted — no entries, no summaries.

    N033：``encoding_override``（'utf-8' | 'declared' | 'detected'）是
    用户经 reparse 诊断显式选择的解码方式，只作用于 Lumi 自己的
    「feed 字节 → 文本」解码点（预览/reparse；FreshRSS 摄取路径的解码
    在上游完成，已投影的历史数据绝不回写）。无法解析出具体编解码器时
    退回原始字节解析（诚实降级，不臆造）。
    """
    payload = raw
    if encoding_override is not None:
        from lumirss.encoding_diag import inspect_encoding, resolve_override_codec

        codec = resolve_override_codec(
            encoding_override, inspect_encoding(raw, content_type)
        )
        if codec is not None:
            try:
                payload = raw.decode(codec, errors="replace")
            except LookupError:
                payload = raw  # unknown codec name: honest raw fallback
    parsed = feedparser.parse(payload)
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
        control,
        *,
        resolver=_default_resolver,
        pin_factory=None,
    ) -> None:
        self._control = control
        self._resolver = resolver
        self._pin_factory = pin_factory

    async def preview(
        self, feed_url: str, *, encoding_override: str | None = None
    ) -> FeedPreview:
        validate_feed_url(feed_url)
        document = await safe_fetch(
            feed_url, resolver=self._resolver, pin_factory=self._pin_factory
        )
        # N033：编码检查始终随预览返回（声明/检测/乱码风险 + 掩码样本）；
        # encoding_override（若提供）只影响本次的解码方式，见
        # parse_feed_document 的诚实边界说明。
        from lumirss.encoding_diag import inspect_encoding

        inspection = inspect_encoding(document.body, document.content_type)
        title, site_url, description, feed_format = parse_feed_document(
            document.body,
            document.content_type,
            encoding_override=encoding_override,
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
            encoding_info=inspection,
        )

    async def reparse(
        self, feed_url: str, *, encoding_override: str | None = None
    ) -> tuple["FetchedDocument", dict, list[dict]]:
        """N033 reparse：同一次有界抓取 + 三种编码选择的真实渲染。

        返回 (document, inspection, choices)；choices 每项是
        {encoding, resolvedCodec, title, sample, mojibakeRisk} —— title
        与 sample 都在该选择下实际解码后提取（乱码如实呈现，不修饰）。
        """
        validate_feed_url(feed_url)
        document = await safe_fetch(
            feed_url, resolver=self._resolver, pin_factory=self._pin_factory
        )
        from lumirss.encoding_diag import (
            decode_sample,
            inspect_encoding,
            resolve_override_codec,
        )

        inspection = inspect_encoding(document.body, document.content_type)
        choices: list[dict] = []
        for choice in ("utf-8", "declared", "detected"):
            codec = resolve_override_codec(choice, inspection)
            sample = decode_sample(document.body, codec)
            parsed_title: str | None = None
            try:
                parsed = feedparser.parse(
                    document.body.decode(codec, errors="replace")
                    if codec
                    else document.body
                )
                raw_title = parsed.feed.get("title")
                if isinstance(raw_title, str) and raw_title.strip():
                    parsed_title = raw_title.strip()[:_MAX_TITLE_LENGTH]
            except Exception:  # noqa: BLE001 — 单选渲染失败如实置空
                parsed_title = None
            choices.append(
                {
                    "encoding": choice,
                    "resolvedCodec": codec,
                    "title": parsed_title,
                    "sample": sample,
                    "mojibakeRisk": "\ufffd" in sample,
                }
            )
        return document, inspection, choices

async def safe_fetch(
    url: str,
    *,
    resolver=_default_resolver,
    max_redirects: int = _MAX_REDIRECTS,
    ensure_public=ensure_public_address,
    pin_factory=None,
) -> "FetchedDocument":
    """Bounded, redirect-aware fetch with per-hop re-validation AND
    pinned dialing.

    Shared by feed preview and source discovery: every hop (including
    redirect targets) passes the same URL/DNS/IP validation as the first
    URL, and the transport dials the VALIDATED address directly. The
    historic validate-then-dial shape left a rebinding window (validate
    resolves public, httpx re-resolves private — Q-P1-03); the pinned
    transport closes it exactly like clip/api-source fetches.
    ``pin_factory`` lets tests stub the underlying transport (same seam
    as clip_fetch).
    """
    if pin_factory is None:
        # Imported here (not at module top): ssrf_transport imports this
        # module's policy primitives, so a top-level import would cycle.
        from lumirss.ssrf_transport import PinnedAddressTransport

        pin_factory = PinnedAddressTransport

    async def validate_hop(hop_url: str) -> None:
        await _require_dialable(resolver, validate_feed_url(hop_url))

    def fail(event: str) -> Exception:
        if event == "no_location":
            return FeedFetchError(
                "Feed URL redirected without a target location."
            )
        return FeedFetchError("Feed URL redirected too many times.")

    transport = pin_factory(resolver=resolver, ensure_public=ensure_public)
    async with httpx.AsyncClient(
        transport=transport,
        trust_env=False,
        follow_redirects=False,
        # Same timeout contract as the shared client (main.py) — the
        # per-call client used to fall back to httpx's 5s default and
        # turned slow feeds into 502s (fresh-eyes P2).
        timeout=httpx.Timeout(10.0, connect=5.0),
    ) as client:
        response, final_url = await follow_redirects(
            url,
            send=lambda hop_url: _send(client, hop_url),
            validate_hop=validate_hop,
            fail=fail,
            max_redirects=max_redirects,
        )
        try:
            if response.status_code != 200:
                raise FeedFetchError(
                    f"The feed URL answered HTTP {response.status_code}."
                )
            return FetchedDocument(
                body=await read_bounded_body(response),
                final_url=final_url,
                content_type=response.headers.get("content-type"),
            )
        finally:
            await response.aclose()


async def _send(client: httpx.AsyncClient, url: str) -> httpx.Response:
    from lumirss.ssrf_transport import UnresolvableHost, UnsafeTargetAddress

    request = client.build_request("GET", url, headers=_HEADERS)
    try:
        # follow_redirects stays OFF: redirects are handled manually so
        # every hop goes through the same validation as the first URL.
        return await client.send(request, stream=True)
    except UnsafeTargetAddress as exc:
        raise UnsafeFeedUrl(str(exc)) from exc
    except UnresolvableHost as exc:
        raise FeedFetchError(
            f"The feed host could not be resolved: {exc}"
        ) from exc
    except httpx.HTTPError as exc:
        raise FeedFetchError("The feed URL could not be reached.") from exc


async def read_bounded_body(response: httpx.Response) -> bytes:
    """Stream a response body with a hard cap (Content-Length fast path +
    streamed read limit). Shared by feed preview, discovery and RSSHub."""
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
