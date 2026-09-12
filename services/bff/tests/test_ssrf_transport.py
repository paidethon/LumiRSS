"""Pinned-dial transport tests (phase2 recovery P0-03).

Proves the DNS-rebinding TOCTOU fix: the transport resolves, validates
ALL addresses, and dials the validated IP directly — with the original
Host header and SNI identity preserved — and that a private answer is
refused before any delegate dial. A real local HTTP server proves the
rewrite works end to end (origin sees the right Host header while the
socket goes to 127.0.0.1).
"""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from lumirss.ssrf_transport import (
    PinnedAddressTransport,
    UnresolvableHost,
    UnsafeTargetAddress,
)


def _run(coro):
    return asyncio.run(coro)


class _RecordingDelegate(httpx.AsyncBaseTransport):
    """Captures what the delegate actually received (no real network)."""

    def __init__(self, *, connect_fail_hosts: set[str] | None = None):
        self.requests: list[dict] = []
        self.connect_fail_hosts = connect_fail_hosts or set()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(
            {
                "url": str(request.url),
                "host": request.url.host,
                "headers_host": request.headers.get("host"),
                "sni": request.extensions.get("sni_hostname"),
            }
        )
        if request.url.host in self.connect_fail_hosts:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, text="ok", request=request)


def test_pins_dial_ip_and_preserves_identity():
    seen = {}

    async def resolver(host, port):
        seen[host] = port
        return ["93.184.216.34"]

    delegate = _RecordingDelegate()
    transport = PinnedAddressTransport(resolver=resolver, delegate=delegate)
    request = httpx.Request("GET", "https://web.example/article?a=1")
    response = _run(transport.handle_async_request(request))
    assert response.status_code == 200
    assert seen == {"web.example": 443}
    entry = delegate.requests[0]
    assert entry["host"] == "93.184.216.34"  # dialed the pinned IP
    assert entry["url"].startswith("https://93.184.216.34/article?a=1")
    assert entry["headers_host"] == "web.example"  # identity preserved
    assert entry["sni"] == "web.example"  # SNI + cert name preserved


def test_private_address_refused_before_any_dial():
    async def resolver(host, port):
        return ["93.184.216.34", "10.0.0.5"]  # one private answer poisons all

    delegate = _RecordingDelegate()
    transport = PinnedAddressTransport(resolver=resolver, delegate=delegate)
    request = httpx.Request("GET", "http://rebind.example/")
    with pytest.raises(UnsafeTargetAddress):
        _run(transport.handle_async_request(request))
    assert delegate.requests == []  # never dialed


def test_resolution_failure_is_stable_error():
    async def resolver(host, port):
        raise OSError(5, "resolver exploded")  # non-gaierror OSError

    delegate = _RecordingDelegate()
    transport = PinnedAddressTransport(resolver=resolver, delegate=delegate)
    request = httpx.Request("GET", "http://broken.example/")
    with pytest.raises(UnresolvableHost):
        _run(transport.handle_async_request(request))
    assert delegate.requests == []


def test_connect_error_falls_through_to_next_validated_address():
    async def resolver(host, port):
        return ["192.0.2.1", "192.0.2.2"]

    delegate = _RecordingDelegate(connect_fail_hosts={"192.0.2.1"})
    transport = PinnedAddressTransport(
        resolver=resolver,
        ensure_public=lambda address: None,  # stub: no real dial happens
        delegate=delegate,
    )
    request = httpx.Request("GET", "http://multi.example/")
    response = _run(transport.handle_async_request(request))
    assert response.status_code == 200
    assert [r["host"] for r in delegate.requests] == ["192.0.2.1", "192.0.2.2"]


def test_non_http_scheme_refused():
    delegate = _RecordingDelegate()
    transport = PinnedAddressTransport(resolver=lambda h, p: ["127.0.0.1"], delegate=delegate)
    request = httpx.Request("GET", "ftp://files.example/x")
    with pytest.raises(UnsafeTargetAddress):
        _run(transport.handle_async_request(request))
    assert delegate.requests == []


# --------------------------------------------------------------------------
# End-to-end against a real local server: dial 127.0.0.1 while the URL
# says a public-looking hostname — the origin must see that Host header.
# --------------------------------------------------------------------------


class _OriginHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — stdlib API
        body = f"host={self.headers.get('host')} path={self.path}".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence test output
        pass


def test_real_socket_dials_pinned_ip_with_original_host():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OriginHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:

        async def resolver(host, port_):
            # The "DNS" stub maps the public-looking name to loopback,
            # exactly what a rebinding/stub resolver would return.
            return ["127.0.0.1"]

        def loopback_ok(address: str) -> None:
            return  # test policy: the "public" name IS loopback here

        async def scenario():
            transport = PinnedAddressTransport(
                resolver=resolver, ensure_public=loopback_ok
            )
            async with httpx.AsyncClient(transport=transport) as client:
                return await client.get(f"http://web.example:{port}/page")

        response = _run(scenario())
        assert response.status_code == 200
        assert f"host=web.example:{port}" in response.text
        assert "path=/page" in response.text
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
