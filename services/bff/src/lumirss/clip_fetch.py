"""SSRF-pinned, budget-bounded page fetch + server-side clip pipeline.

The server is the only network party: the browser never dials the target
site and — since the phase2 recovery — never supplies stored content
either. One bounded fetch through the pinned-dial transport:

    resolve → validate EVERY address → dial the pinned IP → read bytes

with the 00-platform SSRF baseline reused from the feed pipeline:
structural URL validation, credentials refusal, per-hop revalidation
(manual redirects), private / loopback / link-local / reserved /
multicast / CGNAT / NAT64 / IPv4-mapped all refused, response MIME must
be HTML, hard byte cap, chain-level time budget (not per-request). No
cookies or auth headers are ever attached — the fetch is anonymous.

The pinned transport (ssrf_transport.PinnedAddressTransport) closes the
DNS-rebinding TOCTOU: the address that was validated is the address that
is dialed. On top of the fetch, ``fetch_extract_sanitize`` derives the
stored article server-side: extract (article_extract) → sanitize
(article_sanitize, allow-list) → plain text. The browser DOMPurify pass
remains the final render boundary; the server no longer trusts it to do
the cleaning.
"""

import asyncio
import socket
import time
from dataclasses import dataclass

import httpx

from lumirss.article_extract import extract_article
from lumirss.article_sanitize import sanitize_html
from lumirss.feed_preview import (
    UnsafeFeedUrl,
    _default_resolver,
    ensure_public_address,
    follow_redirects,
    validate_feed_url,
)
from lumirss.ssrf_transport import (
    PinnedAddressTransport,
    UnresolvableHost,
    UnsafeTargetAddress,
)

_MAX_PAGE_BYTES = 5 * 1024 * 1024
_FETCH_TIMEOUT_SECONDS = 20.0  # per-request cap ...
_CHAIN_BUDGET_SECONDS = 30.0  # ... but the whole chain is bounded too
_MAX_REDIRECTS = 5
_MAX_TEXT_BYTES = 512 * 1024


class ClipFetchError(Exception):
    """The page could not be fetched (network/HTTP level)."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class ClipForbidden(ClipFetchError):
    """URL refused by the SSRF baseline or non-HTML target."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message, reason)


@dataclass(frozen=True)
class FetchedPage:
    html: str
    final_url: str
    content_type: str


@dataclass(frozen=True)
class ExtractedPage:
    """Fetch + server-side extraction + sanitization, ready to store."""

    url: str
    final_url: str
    title: str
    byline: str | None
    content_html: str
    content_text: str


def validate_clip_url(url: str):
    """Clip URLs share the feed URL structural rules (http/https only)."""
    try:
        return validate_feed_url(url)
    except Exception as exc:  # both error types are ValueError subclasses
        raise ClipForbidden(str(exc), "invalid_url") from exc


async def validate_hop(
    url: str,
    *,
    resolver=_default_resolver,
    ensure_public=ensure_public_address,
) -> None:
    """Structural + resolved-address validation for ONE url (any use).

    Shared by the clip fetch loop and the snapshot runner — a target is
    fully rejected (private / loopback / link-local / metadata / mapped)
    before any network activity or child process is started. The pinned
    transport re-checks at dial time; this is the cheap pre-flight.
    All resolver failures (socket.gaierror is an OSError; both are
    caught) become stable ClipFetchErrors, never 500s. ``resolver`` and
    ``ensure_public`` are injectable so tests run against a local
    origin; production always uses the feed-preview baseline policy.
    """
    parts = validate_clip_url(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        addresses = await resolver(host, port)
    except (socket.gaierror, OSError) as exc:
        raise ClipFetchError("页面地址无法解析。", "dns_failure") from exc
    if not addresses:
        raise ClipFetchError("页面地址解析为空。", "dns_failure")
    from lumirss.feed_preview import hostname_allowlisted

    allowlisted = hostname_allowlisted(host)
    for address in addresses:
        if allowlisted:
            break  # operator vouched for this hostname; still dial pinned IPs
        try:
            ensure_public(address)
        except (ValueError, UnsafeFeedUrl) as exc:
            raise ClipForbidden(
                "页面地址解析到非公网地址，已拒绝。", "unsafe_address"
            ) from exc


async def fetch_page(
    url: str,
    *,
    resolver=_default_resolver,
    ensure_public=ensure_public_address,
    pin_factory=PinnedAddressTransport,
) -> FetchedPage:
    """One anonymous, bounded, SSRF-pinned HTML fetch.

    ``resolver`` (raw getaddrinfo-style) and ``ensure_public`` are
    injectable so tests never hit real DNS or the public internet; they
    thread into both the pre-flight hop validation and the pinned
    transport that dials the validated address. ``pin_factory`` lets
    tests inject a stub delegate behind the same pinning logic.
    """
    validate_clip_url(url)

    transport = pin_factory(resolver=resolver, ensure_public=ensure_public)
    deadline = time.monotonic() + _CHAIN_BUDGET_SECONDS
    loop = asyncio.get_running_loop()

    async def send(target: str) -> httpx.Response:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise ClipFetchError(
                f"页面抓取超过 {_CHAIN_BUDGET_SECONDS:.0f}s 链路预算。", "timeout"
            )
        try:
            return await asyncio.wait_for(
                client.get(
                    target,
                    follow_redirects=False,
                    headers={"accept": "text/html,application/xhtml+xml"},
                ),
                timeout=min(_FETCH_TIMEOUT_SECONDS, remaining),
            )
        except TimeoutError:
            raise ClipFetchError("页面抓取超时。", "timeout") from None
        except httpx.HTTPError as exc:
            raise ClipFetchError("页面抓取失败。", "fetch_failed") from exc

    async def validate(target: str) -> None:
        await validate_hop(target, resolver=resolver, ensure_public=ensure_public)

    def fail(reason: str) -> Exception:
        mapping = {
            "no_location": ("重定向缺少目标。", "fetch_failed"),
            "too_many_redirects": ("重定向次数过多。", "fetch_failed"),
        }
        message, code = mapping.get(reason, ("页面抓取失败。", reason))
        return ClipFetchError(message, code)

    try:
        async with httpx.AsyncClient(
            transport=transport, trust_env=False, follow_redirects=False
        ) as client:
            try:
                async with asyncio.timeout(_CHAIN_BUDGET_SECONDS):
                    response, final_url = await follow_redirects(
                        url,
                        send=send,
                        validate_hop=validate,
                        fail=fail,
                        max_redirects=_MAX_REDIRECTS,
                    )
                    try:
                        if response.status_code != 200:
                            reason = (
                                "forbidden"
                                if response.status_code in (401, 403)
                                else "fetch_failed"
                            )
                            raise ClipFetchError(
                                f"页面返回 HTTP {response.status_code}。", reason
                            )
                        content_type = response.headers.get(
                            "content-type", ""
                        ).lower()
                        if "html" not in content_type and "xml" not in content_type:
                            raise ClipForbidden(
                                f"目标不是网页（content-type: {content_type or '未知'}）。",
                                "bad_mime",
                            )
                        declared = response.headers.get("content-length")
                        if (
                            declared
                            and declared.isdigit()
                            and int(declared) > _MAX_PAGE_BYTES
                        ):
                            raise ClipFetchError(
                                "页面超过 5MB 大小上限。", "too_large"
                            )
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > _MAX_PAGE_BYTES:
                                raise ClipFetchError(
                                    "页面超过 5MB 大小上限。", "too_large"
                                )
                        return FetchedPage(
                            html=bytes(body).decode("utf-8", errors="replace"),
                            final_url=final_url,
                            content_type=content_type,
                        )
                    finally:
                        await response.aclose()
            except TimeoutError:
                raise ClipFetchError(
                    f"页面抓取超过 {_CHAIN_BUDGET_SECONDS:.0f}s 链路预算。",
                    "timeout",
                ) from None
    except UnresolvableHost as exc:
        raise ClipFetchError("页面地址无法解析。", "dns_failure") from exc
    except UnsafeTargetAddress as exc:
        raise ClipForbidden(
            "页面地址解析到非公网地址，已拒绝。", "unsafe_address"
        ) from exc


async def fetch_extract_sanitize(
    url: str,
    *,
    resolver=_default_resolver,
    ensure_public=ensure_public_address,
) -> ExtractedPage:
    """Full server-side pipeline: fetch → extract → sanitize → text.

    Everything the clip store persists is produced here, on the server;
    client-supplied HTML never enters the pipeline.
    """
    from lumirss.adapters.freshrss import AdapterError, html_to_text

    page = await fetch_page(url, resolver=resolver, ensure_public=ensure_public)
    article = extract_article(page.html)
    clean_html = sanitize_html(article.content_html, base_url=page.final_url)
    if not clean_html.strip():
        raise ClipFetchError("无法从页面提取正文。", "extract_failed")
    try:
        text = html_to_text(clean_html)
    except AdapterError:
        text = article.content_text
    title = article.title or page.final_url
    return ExtractedPage(
        url=url,
        final_url=page.final_url,
        title=title[:500],
        byline=(article.byline or None),
        content_html=clean_html,
        content_text=text[:_MAX_TEXT_BYTES],
    )
