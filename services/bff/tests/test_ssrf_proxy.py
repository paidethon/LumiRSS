"""SSRF filtering proxy tests (phase2 recovery P0-04).

The proxy is what makes remote snapshots enforceable: monolith's
sub-resource fetches arrive here (absolute-URI http or CONNECT https)
and must be resolved, policy-checked, and dialed on the pinned IP —
with private/unresolvable targets refused before any byte is forwarded.
Tests drive it the way monolith does: httpx with a proxy for plain
HTTP, and a raw socket for CONNECT.
"""

import asyncio
import ipaddress
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

from lumirss.feed_preview import ensure_public_address
from lumirss.ssrf_proxy import SsrfFilteringProxy


def _test_policy(address: str) -> None:
    """Production address rules, plus loopback (tests tunnel to a local
    origin server — that is the one thing production forbids)."""
    ip = ipaddress.ip_address(address)
    if ip.is_loopback:
        return
    ensure_public_address(address)


def _run(coro):
    return asyncio.run(coro)


class _OriginHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — stdlib API
        body = f"origin-hit host={self.headers.get('host')} path={self.path}".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _Origin:
    """Local origin server + stub resolver mapping a public name to it."""

    def __init__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _OriginHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

        async def resolver(host, port):
            if host == "origin.example":
                return ["127.0.0.1"]
            if host == "unresolvable.example":
                raise OSError(-2, "Name or service not known")
            return ["203.0.113.1"]  # reserved TEST-NET-3 → policy-refused

        self.resolver = resolver

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        _ = self.thread


def test_plain_http_proxied_through_pinned_origin():
    origin = _Origin()
    try:

        async def scenario():
            proxy = SsrfFilteringProxy(
                resolver=origin.resolver, ensure_public=_test_policy
            )
            async with proxy:
                async with httpx.AsyncClient(proxy=proxy.url, trust_env=False) as client:
                    return await client.get(f"http://origin.example:{origin.port}/page?x=1")

        response = _run(scenario())
        assert response.status_code == 200
        assert "origin-hit" in response.text
        assert f"host=origin.example:{origin.port}" in response.text  # Host preserved
        assert "path=/page?x=1" in response.text  # origin-form rewrite
    finally:
        origin.stop()


def test_private_target_refused_without_dial():
    origin = _Origin()
    try:

        async def scenario():
            proxy = SsrfFilteringProxy(
                resolver=origin.resolver, ensure_public=_test_policy
            )
            async with proxy:
                async with httpx.AsyncClient(proxy=proxy.url, trust_env=False) as client:
                    response = await client.get("http://10.9.9.9/secret")
                    return response.status_code

        assert _run(scenario()) == 403  # fail-closed: proxy refuses (no dial)
    finally:
        origin.stop()


def test_unresolvable_target_refused():
    origin = _Origin()
    try:

        async def scenario():
            proxy = SsrfFilteringProxy(
                resolver=origin.resolver, ensure_public=_test_policy
            )
            async with proxy:
                async with httpx.AsyncClient(proxy=proxy.url, trust_env=False) as client:
                    try:
                        response = await client.get("http://unresolvable.example/x")
                        return response.status_code
                    except httpx.HTTPError:
                        return "transport-error"

        assert _run(scenario()) == 403
    finally:
        origin.stop()


def test_reserved_testnet_target_refused():
    origin = _Origin()
    try:

        async def scenario():
            proxy = SsrfFilteringProxy(
                resolver=origin.resolver, ensure_public=_test_policy
            )
            async with proxy:
                async with httpx.AsyncClient(proxy=proxy.url, trust_env=False) as client:
                    try:
                        response = await client.get("http://testnet.example/x")
                        return response.status_code
                    except httpx.HTTPError:
                        return "transport-error"

        assert _run(scenario()) == 403
    finally:
        origin.stop()


def test_connect_tunnel_validates_then_pins():
    """CONNECT to a public name: validated, 200, then bytes flow to the
    PINNED address (here: a plain local server acting as tunnel target)."""
    origin = _Origin()
    try:

        def scenario():
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_connect_flow(origin))
            finally:
                loop.close()

        async def _connect_flow(origin):
            proxy = SsrfFilteringProxy(
                resolver=origin.resolver, ensure_public=_test_policy
            )
            await proxy.start()
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
                writer.write(
                    f"CONNECT origin.example:{origin.port} HTTP/1.1\r\nHost: origin.example:{origin.port}\r\n\r\n".encode()
                )
                await writer.drain()
                status_line = await reader.readuntil(b"\r\n\r\n")
                assert b"200" in status_line.split(b"\r\n")[0]
                writer.write(
                    f"GET /tunneled HTTP/1.1\r\nHost: origin.example:{origin.port}\r\nConnection: close\r\n\r\n".encode()
                )
                await writer.drain()
                payload = await reader.read()
                writer.close()
                return status_line, payload
            finally:
                await proxy.stop()

        _status, payload = scenario()
        assert b"origin-hit" in payload
        assert b"path=/tunneled" in payload
    finally:
        origin.stop()


def test_connect_to_private_refused_without_tunnel():
    origin = _Origin()
    try:

        def scenario():
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_connect_flow(origin))
            finally:
                loop.close()

        async def _connect_flow(origin):
            proxy = SsrfFilteringProxy(
                resolver=origin.resolver, ensure_public=_test_policy
            )
            await proxy.start()
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
                writer.write(b"CONNECT 169.254.169.254:80 HTTP/1.1\r\n\r\n")
                await writer.drain()
                head = await reader.read(4096)
                writer.close()
                return head
            finally:
                await proxy.stop()

        head = scenario()
        assert head.startswith(b"HTTP/1.1 403")
    finally:
        origin.stop()


def test_garbage_request_gets_error_not_crash():
    async def scenario():
        proxy = SsrfFilteringProxy(resolver=lambda h, p: ["127.0.0.1"])
        await proxy.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
            writer.write(b"NOT A REQUEST\r\n\r\n")
            await writer.drain()
            head = await reader.read(4096)
            writer.close()
            return head
        finally:
            await proxy.stop()

    head = _run(scenario())
    # Garbage must be answered (403 = fail-closed refuse), never crash.
    assert head.startswith(b"HTTP/1.1 403")
