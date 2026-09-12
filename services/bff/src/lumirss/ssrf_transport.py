"""SSRF-pinned dialing for httpx (phase2 recovery P0-03).

``validate-then-dial`` has a TOCTOU hole: the validator resolves the
hostname and checks every address, then httpx re-resolves independently
when it dials — a rebinding DNS server can answer with a public address
for the check and a private address for the dial. This transport closes
the hole by owning resolution itself:

    resolve → validate EVERY address → dial the chosen IP directly

Mechanics (verified against httpx 0.28 / httpcore 1.0):

- the request keeps its original ``Host`` header (set at build time from
  the original URL), so origin servers see the real hostname;
- for https the ``sni_hostname`` request extension carries the original
  hostname into httpcore, which uses it for both SNI and certificate
  verification — only the TCP destination is pinned;
- every request through this transport is re-resolved and re-validated,
  including every manual redirect hop, so no path can bypass the address
  policy.

Error model: ``UnresolvableHost`` (DNS-level failure) and
``UnsafeTargetAddress`` (policy refusal) are plain exceptions; callers
map them onto their own domain errors. Connect errors on the first
pinned candidate fall through to the next validated address (bounded);
other errors propagate untouched.
"""

import socket

import httpx

from lumirss.feed_preview import (
    UnsafeFeedUrl,
    _default_resolver,
    ensure_public_address,
)

# Cap on how many validated addresses one request may try (connect
# failures only). Keeps a hostile DNS answer with hundreds of records
# from stretching one request into a long retry loop.
_MAX_PINNED_CANDIDATES = 4


class UnresolvableHost(Exception):
    """The hostname could not be resolved (DNS-level failure)."""


class UnsafeTargetAddress(Exception):
    """The hostname resolved to (or requested) a non-public address."""


def _validate_schemes(url: httpx.URL) -> None:
    if url.scheme not in ("http", "https"):
        raise UnsafeTargetAddress(f"Scheme {url.scheme!r} is not dialable.")


async def resolve_validated(
    host: str,
    port: int,
    *,
    resolver=_default_resolver,
    ensure_public=ensure_public_address,
) -> list[str]:
    """Resolve ``host`` and return the addresses that pass the policy.

    Raises UnresolvableHost for DNS failures (socket.gaierror is an
    OSError; both are caught here — the pre-recovery code let non-gai
    OSErrors escape as 500s) and UnsafeTargetAddress when ANY resolved
    address is non-public (same all-address rule as feed preview).
    ``ensure_public`` is the policy callable; tests may inject a
    variant (e.g. loopback-permitting) but production always uses the
    feed-preview baseline.
    """
    try:
        addresses = await resolver(host, port)
    except (socket.gaierror, OSError) as exc:
        raise UnresolvableHost(f"Host {host!r} could not be resolved.") from exc
    if not addresses:
        raise UnresolvableHost(f"Host {host!r} resolved to no addresses.")
    from lumirss.feed_preview import hostname_allowlisted

    allowlisted = hostname_allowlisted(host)
    validated: list[str] = []
    for address in addresses:
        if allowlisted:
            validated.append(address)
            continue  # operator vouched for this hostname; still dial pinned
        try:
            ensure_public(address)
        except (ValueError, UnsafeFeedUrl, UnsafeTargetAddress) as exc:
            raise UnsafeTargetAddress(
                f"Host {host!r} resolves to a non-public address."
            ) from exc
        if address not in validated:
            validated.append(address)
    return validated


class PinnedAddressTransport(httpx.AsyncHTTPTransport):
    """httpx transport that dials validated addresses directly.

    ``delegate`` is the underlying transport actually performing I/O;
    tests inject a stub here, production uses a plain httpx transport
    with trust_env off (no ambient proxies for server-side fetches).
    """

    def __init__(
        self,
        *,
        resolver=_default_resolver,
        ensure_public=ensure_public_address,
        delegate: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._resolver = resolver
        self._ensure_public = ensure_public
        self._delegate = delegate
        self._owned = None

    def _delegate_for(self) -> httpx.AsyncBaseTransport:
        if self._delegate is None:
            if self._owned is None:
                self._owned = httpx.AsyncHTTPTransport(trust_env=False)
            return self._owned
        return self._delegate

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        _validate_schemes(request.url)
        host = request.url.host
        if not host:
            raise UnsafeTargetAddress("Request URL names no host.")
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        original_url = request.url
        original_host = host
        candidates = (
            await resolve_validated(
                host, port, resolver=self._resolver, ensure_public=self._ensure_public
            )
        )[:_MAX_PINNED_CANDIDATES]
        last_connect_error: httpx.ConnectError | None = None
        for address in candidates:
            pinned_request = _pinned_copy(
                request, original_url, original_host, address
            )
            try:
                return await self._delegate_for().handle_async_request(pinned_request)
            except httpx.ConnectError as exc:  # pre-send dial failure only
                last_connect_error = exc
        if last_connect_error is not None:
            raise last_connect_error
        raise UnresolvableHost(f"Host {host!r} had no dialable address.")

    async def aclose(self) -> None:
        if self._owned is not None:
            await self._owned.aclose()
        if self._delegate is not None:
            close = getattr(self._delegate, "aclose", None)
            if close is not None:
                await close()

    async def __aenter__(self) -> "PinnedAddressTransport":
        # httpx.AsyncClient awaits its transport as a context manager;
        # forward to the delegate that actually owns the pool.
        enter = getattr(self._delegate_for(), "__aenter__", None)
        if enter is not None:
            await enter()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()


def _pinned_copy(
    request: httpx.Request,
    original_url: httpx.URL,
    original_host: str,
    address: str,
) -> httpx.Request:
    """Rebuild ``request`` so it dials ``address`` with original identity.

    Host header stays (it was set from the original URL and is copied
    verbatim); ``sni_hostname`` restores the real hostname for SNI and
    certificate verification on TLS connections.
    """
    pinned_url = original_url.copy_with(host=address)
    extensions = dict(request.extensions)
    extensions["sni_hostname"] = original_host
    return httpx.Request(
        request.method,
        pinned_url,
        headers=request.headers,
        stream=request.stream,
        extensions=extensions,
    )
