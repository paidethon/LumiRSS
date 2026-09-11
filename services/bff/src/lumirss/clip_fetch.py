"""SSRF-guarded bounded page fetch for web clipping (phase2 M2).

The server is the only network party: the browser never dials the target
site. One bounded fetch with the 00-platform SSRF baseline reused from
the feed pipeline: structural URL validation, credentials refusal, DNS
resolution checked before every dial (private / loopback / link-local /
reserved / multicast / CGNAT / NAT64 / IPv4-mapped all refused), manual
redirect following with per-hop revalidation, response MIME must be
HTML, hard byte cap and timeout. No cookies or auth headers are ever
attached — the fetch is anonymous.
"""

import asyncio
import socket
import urllib.parse
from dataclasses import dataclass

import httpx

from lumirss.feed_preview import (
    UnsafeFeedUrl,
    _default_resolver,
    ensure_public_address,
    follow_redirects,
    validate_feed_url,
)

_MAX_PAGE_BYTES = 5 * 1024 * 1024
_FETCH_TIMEOUT_SECONDS = 20.0
_MAX_REDIRECTS = 5


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


def validate_clip_url(url: str) -> urllib.parse.SplitResult:
    """Clip URLs share the feed URL structural rules (http/https only)."""
    try:
        return validate_feed_url(url)
    except Exception as exc:  # both error types are ValueError subclasses
        raise ClipForbidden(str(exc), "invalid_url") from exc


async def validate_hop(url: str) -> None:
    """Structural + resolved-address validation for ONE url (any use).

    Shared by the clip fetch loop and the snapshot runner — a target is
    fully rejected (private / loopback / link-local / metadata / mapped)
    before any network activity or child process is started.
    """
    parts = validate_clip_url(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        addresses = await _default_resolver(host, port)
    except socket.gaierror as exc:
        raise ClipFetchError("页面地址无法解析。", "dns_failure") from exc
    if not addresses:
        raise ClipForbidden("页面地址解析为空。", "dns_failure")
    for address in addresses:
        try:
            ensure_public_address(address)
        except (ValueError, UnsafeFeedUrl) as exc:
            raise ClipForbidden(
                "页面地址解析到非公网地址，已拒绝。", "unsafe_address"
            ) from exc


async def fetch_page(http_client: httpx.AsyncClient, url: str) -> FetchedPage:
    """One anonymous, bounded, SSRF-guarded HTML fetch."""
    await validate_hop(url)

    async def send(target: str) -> httpx.Response:
        return await asyncio.wait_for(
            http_client.get(
                target,
                follow_redirects=False,
                headers={"accept": "text/html,application/xhtml+xml"},
            ),
            timeout=_FETCH_TIMEOUT_SECONDS,
        )

    async def validate(target: str) -> None:
        await validate_hop(target)

    def fail(reason: str) -> Exception:
        mapping = {
            "no_location": ("重定向缺少目标。", "fetch_failed"),
            "too_many_redirects": ("重定向次数过多。", "fetch_failed"),
        }
        message, code = mapping.get(reason, ("页面抓取失败。", reason))
        return ClipFetchError(message, code)

    response, final_url = await follow_redirects(
        url,
        send=send,
        validate_hop=validate,
        fail=fail,
        max_redirects=_MAX_REDIRECTS,
    )
    try:
        if response.status_code != 200:
            reason = "forbidden" if response.status_code in (401, 403) else "fetch_failed"
            raise ClipFetchError(
                f"页面返回 HTTP {response.status_code}。", reason
            )
        content_type = response.headers.get("content-type", "").lower()
        if "html" not in content_type and "xml" not in content_type:
            raise ClipForbidden(
                f"目标不是网页（content-type: {content_type or '未知'}）。",
                "bad_mime",
            )
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > _MAX_PAGE_BYTES:
            raise ClipFetchError("页面超过 5MB 大小上限。", "too_large")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > _MAX_PAGE_BYTES:
                raise ClipFetchError("页面超过 5MB 大小上限。", "too_large")
        return FetchedPage(
            html=bytes(body).decode("utf-8", errors="replace"),
            final_url=final_url,
            content_type=content_type,
        )
    finally:
        await response.aclose()
