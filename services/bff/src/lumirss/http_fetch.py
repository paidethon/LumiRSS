"""Shared bounded redirect-following for outbound HTTP.

One canonical implementation of the redirect loop that feed preview,
RSSHub and the WebDAV client previously each maintained by hand: hops
are followed manually (follow_redirects stays off) so every hop passes
the caller's own validation — public-IP SSRF re-validation for untrusted
feed URLs, strict in-origin pinning for configured infrastructure.
Callers keep ownership of transport details (headers, auth, timeouts,
error types and exact wire messages) via the send/validate_hop/fail
callbacks; this module only owns the loop mechanics.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Awaitable, Callable

import httpx

REDIRECT_STATUSES = (301, 302, 303, 307, 308)


async def follow_redirects(
    start_url: str,
    *,
    send: Callable[[str], Awaitable[httpx.Response]],
    validate_hop: Callable[[str], Awaitable[None]],
    fail: Callable[[str], Exception],
    max_redirects: int = 5,
) -> tuple[httpx.Response, str]:
    """Follow 3xx responses manually, at most ``max_redirects`` hops.

    ``validate_hop(url)`` runs before every request (including the
    first). Redirect responses are closed here; the final response is
    returned open — the caller reads/closes it. ``fail`` builds the
    caller's own error type (with its exact wire message) for the
    loop-level failures: ``fail("no_location")`` and
    ``fail("too_many_redirects")``. Non-redirect statuses are returned
    to the caller — what counts as success differs per domain
    (feeds require 200; WebDAV verbs have meaningful non-200s).
    """
    current = start_url
    for _hop in range(max_redirects + 1):
        await validate_hop(current)
        response = await send(current)
        if response.status_code in REDIRECT_STATUSES:
            location = response.headers.get("location")
            await response.aclose()
            if not location:
                raise fail("no_location")
            current = urllib.parse.urljoin(current, location)
            continue
        return response, current
    raise fail("too_many_redirects")


def origin_of(url: str) -> str:
    """Lowercased scheme+host[:port] of ``url`` (in-origin pinning)."""
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), "", "", ""))
