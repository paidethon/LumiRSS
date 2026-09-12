"""In-process SSRF-filtering forward proxy for monolith (P0-04).

monolith's own sub-resource fetches cannot be intercepted in-process,
and it has no allow-list capability — but it DOES honor the standard
proxy environment variables (verified empirically against monolith
2.10.1: page, sub-resources and favicon requests all arrive at
HTTP_PROXY in absolute-URI form; HTTPS goes through CONNECT). So the
snapshot runner starts this local proxy and points the child process at
it, giving every request monolith makes the SAME address policy the
clip pipeline enforces:

    resolve → validate EVERY address (ensure_public_address) → dial the
    pinned IP ourselves → only then forward bytes

- plain http: absolute-URI request line → validate → rewrite to
  origin-form → connect to the pinned IP → stream both directions;
- https CONNECT: authority-form host:port → validate → 200 → blind TCP
  tunnel to the pinned IP (TLS stays end-to-end between monolith and
  the origin; the address policy was enforced at dial time, so no
  rebinding is possible);
- fail-closed: unresolvable hosts, non-public addresses (private /
  loopback / link-local / reserved / multicast / CGNAT / NAT64 /
  IPv4-mapped), non-http(s) schemes and malformed requests are refused
  before a byte is forwarded.

The proxy listens on 127.0.0.1 with an ephemeral port, lives only for
the duration of one snapshot run, and buffers nothing but the request
head (bounded). Per-connection work is bounded by an idle timeout; the
snapshot wall clock bounds the whole run anyway.
"""

import asyncio
import contextlib
import urllib.parse

from lumirss.feed_preview import _default_resolver, ensure_public_address
from lumirss.ssrf_transport import (
    UnresolvableHost,
    UnsafeTargetAddress,
    resolve_validated,
)

_MAX_HEAD_BYTES = 64 * 1024
_IDLE_TIMEOUT_SECONDS = 90.0


class ProxyRefused(Exception):
    """A proxied request violated the address policy (fail-closed)."""


class SsrfFilteringProxy:
    """Local forward proxy enforcing the Lumi address policy."""

    def __init__(
        self,
        *,
        resolver=_default_resolver,
        ensure_public=ensure_public_address,
    ) -> None:
        self._resolver = resolver
        self._ensure_public = ensure_public
        self._server: asyncio.Server | None = None
        self.port: int | None = None

    @property
    def url(self) -> str:
        if self.port is None:
            raise RuntimeError("Proxy not started.")
        return f"http://127.0.0.1:{self.port}"

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, "127.0.0.1", 0
        )
        self.port = int(self._server.sockets[0].getsockname()[1])

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            self.port = None

    async def __aenter__(self) -> "SsrfFilteringProxy":
        await self.start()
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.stop()

    # -- connection handling ------------------------------------------------

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            head = await asyncio.wait_for(
                reader.readuntil(b"\r\n\r\n"), timeout=15.0
            )
        except (TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
            _close(writer)
            return
        if len(head) > _MAX_HEAD_BYTES:
            _refuse(writer, "431 Request Header Fields Too Large")
            return
        try:
            request_line = head.split(b"\r\n", 1)[0].decode("latin-1")
            method, target, _version = request_line.split(" ", 2)
        except ValueError:
            _refuse(writer, "400 Bad Request")
            return
        try:
            if method == "CONNECT":
                await self._handle_connect(target, reader, writer)
            else:
                await self._handle_plain(method, target, head, reader, writer)
        except (ProxyRefused, UnresolvableHost, UnsafeTargetAddress, ValueError):
            _refuse(writer, "403 Forbidden")
        except OSError:
            _refuse(writer, "502 Bad Gateway")
        finally:
            _close(writer)

    async def _validate_target(self, host: str, port: int) -> str:
        """Resolve + validate; return the ONE pinned dial address."""
        if not host or not (0 < port < 65536):
            raise ProxyRefused(f"Invalid authority {host!r}:{port}.")
        addresses = await resolve_validated(
            host, port, resolver=self._resolver, ensure_public=self._ensure_public
        )
        return addresses[0]

    async def _handle_connect(self, authority, reader, writer) -> None:
        host, port = _split_authority(authority, default_port=443)
        address = await self._validate_target(host, port)
        try:
            origin_reader, origin_writer = await asyncio.wait_for(
                asyncio.open_connection(address, port), timeout=15.0
            )
        except (TimeoutError, OSError) as exc:
            raise OSError("CONNECT dial failed") from exc
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()
        await _pipe_both(reader, writer, origin_reader, origin_writer)

    async def _handle_plain(self, method, target, head, reader, writer) -> None:
        parts = urllib.parse.urlsplit(target)
        if parts.scheme != "http" or not parts.hostname:
            raise ProxyRefused(f"Non-http proxy target {target!r}.")
        port = parts.port or 80
        address = await self._validate_target(parts.hostname, port)
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        # Rewrite to origin-form; keep the client's headers verbatim
        # (monolith already set Host for the real origin).
        origin_head = head.replace(
            b" " + target.encode("latin-1") + b" ",
            b" " + path.encode("latin-1") + b" ",
            1,
        )
        try:
            origin_reader, origin_writer = await asyncio.wait_for(
                asyncio.open_connection(address, port), timeout=15.0
            )
        except (TimeoutError, OSError) as exc:
            raise OSError("Proxy dial failed") from exc
        origin_writer.write(origin_head)
        await origin_writer.drain()
        await _pipe_both(reader, writer, origin_reader, origin_writer)


# -- helpers ---------------------------------------------------------------


def _split_authority(authority: str, *, default_port: int) -> tuple[str, int]:
    if authority.startswith("["):  # IPv6 literal
        host, _, rest = authority[1:].partition("]")
        port = int(rest[1:]) if rest.startswith(":") else default_port
        return host, port
    host, _, port_part = authority.rpartition(":")
    if not host:
        return authority, default_port
    return host, int(port_part)


async def _pipe_both(client_reader, client_writer, origin_reader, origin_writer) -> None:
    async def one_way(src, dst) -> None:
        try:
            while True:
                data = await src.read(64 * 1024)
                if not data:
                    break
                dst.write(data)
                await dst.drain()
        except (ConnectionError, TimeoutError, OSError):
            pass
        finally:
            with contextlib.suppress(OSError):
                dst.close()

    try:
        await asyncio.wait_for(
            asyncio.gather(
                one_way(client_reader, origin_writer),
                one_way(origin_reader, client_writer),
            ),
            timeout=_IDLE_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        pass
    finally:
        for writer in (client_writer, origin_writer):
            _close(writer)


def _refuse(writer, status: str) -> None:
    with contextlib.suppress(ConnectionError, OSError):
        writer.write(
            f"HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode()
        )
    _close(writer)


def _close(writer) -> None:
    with contextlib.suppress(OSError):
        writer.close()
