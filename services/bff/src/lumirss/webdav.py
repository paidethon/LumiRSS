"""Server-side WebDAV client (0018) — httpx only, bounded, redacted.

The browser never talks to WebDAV directly; all operations go through the
BFF. Supported operations are exactly what backup needs: MKCOL / PUT / GET /
PROPFIND(depth 1) / DELETE (within the backup root only).

URL policy (trusted operator configuration, distinct from untrusted source
URLs):
- absolute http(s) only; credentials/query/fragment rejected;
- http is only allowed for literal loopback/private IPs or "localhost";
- https verifies TLS by default (tlsVerify may be explicitly disabled for
  self-signed servers);
- redirects are bounded and must stay within the same origin.

No URLs, usernames or credentials ever appear in error messages returned to
the client — every failure is mapped to a stable, static, browser-safe
message.
"""

import ipaddress
import os
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import httpx
from defusedxml import ElementTree

_MAX_REDIRECTS = 5
_MAX_RESPONSE_BYTES = 256 * 1024 * 1024  # 256 MiB bound for downloaded backups
_MAX_LIST_BYTES = 8 * 1024 * 1024  # 8 MiB bound for PROPFIND listings
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def quote_path_segment(segment: str) -> str:
    """Percent-encode one path segment for use in a request URL."""
    return urllib.parse.quote(segment, safe="")


class WebDavNotConfigured(Exception):
    """WebDAV settings are missing or invalid."""


class WebDavError(Exception):
    """A WebDAV operation failed (safe message only)."""


class WebDavInvalidSettings(WebDavError):
    """Client-supplied WebDAV settings are structurally invalid.

    AUDIT: blank URL / unsupported scheme / credentials in URL / traversal in
    the remote dir are CLIENT-INPUT errors and must surface as a stable 4xx,
    not the 502 reserved for real upstream failures. Subclasses WebDavError so
    existing ``raises(WebDavError)`` expectations still hold while main.py maps
    this specific type to 400."""


@dataclass(frozen=True)
class WebDavSettings:
    server_url: str
    username: str
    remote_dir: str
    tls_verify: bool


def _is_private_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        address.is_loopback
        or address.is_private
        or address.is_link_local
    )


def normalize_server_url(value: str) -> str:
    """Structural validation of the WebDAV server URL."""
    clean = value.strip()
    if not clean:
        raise WebDavInvalidSettings("WebDAV server URL must not be blank.")
    parts = urllib.parse.urlsplit(clean)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise WebDavInvalidSettings("WebDAV server URL must be an absolute http(s) URL.")
    if parts.username or parts.password:
        raise WebDavInvalidSettings("WebDAV server URL must not carry credentials.")
    if parts.query or parts.fragment:
        raise WebDavInvalidSettings("WebDAV server URL must not carry a query or fragment.")
    host = (parts.hostname or "").lower()
    if not host:
        raise WebDavInvalidSettings("WebDAV server URL is missing a host.")
    if parts.scheme == "http" and not _is_private_host(host):
        raise WebDavInvalidSettings(
            "http WebDAV is only allowed for loopback/private addresses; use https."
        )
    return clean.rstrip("/")


def normalize_remote_dir(value: str) -> str:
    """Normalize the remote directory; reject traversal/absolute weirdness."""
    clean = (value or "").strip()
    if not clean:
        return ""
    parts = urllib.parse.urlsplit(clean)
    if parts.scheme or parts.netloc:
        raise WebDavInvalidSettings("remote directory must be a path, not a URL.")
    if clean == "/":
        return ""
    segments = [seg for seg in clean.split("/") if seg not in ("", ".")]
    if any(seg == ".." for seg in segments):
        raise WebDavInvalidSettings("remote directory must not contain '..'.")
    return "/" + "/".join(segments)


def _join_path(base: str, *parts: str) -> str:
    """Join path segments safely (no '..' allowed in any part)."""
    segments: list[str] = []
    for part in (base, *parts):
        for seg in part.split("/"):
            if seg in ("", "."):
                continue
            if seg == "..":
                raise WebDavError("invalid path segment")
            segments.append(seg)
    if not segments:
        return "/"
    return "/" + "/".join(urllib.parse.quote(seg, safe="-_.") for seg in segments)


def backup_remote_path(remote_dir: str, year: str, month: str, filename: str) -> str:
    """Stable remote layout: <dir>/LumiRSS/backups/<YYYY>/<MM>/<file>."""
    return _join_path(remote_dir, "LumiRSS", "backups", year, month, filename)


def backup_root_path(remote_dir: str) -> str:
    """The LumiRSS backup root on the remote: <dir>/LumiRSS/backups."""
    return _join_path(remote_dir, "LumiRSS", "backups")


class WebDavClient:
    """Bounded WebDAV operations over a dedicated httpx client.

    The client is built with the operator's ``tlsVerify`` setting (httpx sets
    ``verify`` at client construction, not per request). Tests may inject a
    ``transport`` (e.g. httpx.MockTransport) to avoid any real network.
    """

    def __init__(
        self,
        settings: WebDavSettings,
        password: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._auth = httpx.BasicAuth(settings.username, password)
        self._client = httpx.AsyncClient(
            verify=settings.tls_verify,
            trust_env=False,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _url(self, path: str) -> str:
        return f"{self._settings.server_url}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        origin = urllib.parse.urlsplit(self._settings.server_url)
        base_origin = urllib.parse.urlunsplit(
            (origin.scheme.lower(), origin.netloc.lower(), "", "", "")
        )
        current = base_origin + path
        for _hop in range(_MAX_REDIRECTS + 1):
            parts = urllib.parse.urlsplit(current)
            hop_origin = urllib.parse.urlunsplit(
                (parts.scheme.lower(), parts.netloc.lower(), "", "", "")
            )
            if hop_origin != base_origin:
                raise WebDavError("WebDAV redirected outside its origin.")
            try:
                response = await self._client.request(
                    method,
                    current,
                    content=content,
                    headers=headers,
                    auth=self._auth,
                    timeout=_TIMEOUT,
                )
            except httpx.HTTPError:
                raise WebDavError("Could not reach the WebDAV server.") from None
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    raise WebDavError("WebDAV redirected without a location.")
                current = urllib.parse.urljoin(current, location)
                continue
            return response
        raise WebDavError("WebDAV redirected too many times.")

    async def ensure_dir(self, path: str) -> None:
        """MKCOL each segment; already-exists (405/409/301) is fine."""
        segments = [seg for seg in path.split("/") if seg]
        current = ""
        for segment in segments:
            current = f"{current}/{urllib.parse.quote(segment, safe='-_')}"
            response = await self._request("MKCOL", current)
            status = response.status_code
            await response.aclose()
            if status in (201, 204):
                continue
            if status in (301, 405, 409):
                continue
            raise WebDavError("Could not create the remote backup directory.")

    async def put(self, path: str, data: bytes) -> None:
        response = await self._request(
            "PUT", path, content=data, headers={"Content-Type": "application/octet-stream"}
        )
        status = response.status_code
        await response.aclose()
        if status not in (200, 201, 204):
            raise WebDavError("Could not upload the backup to WebDAV.")

    async def get(self, path: str) -> bytes:
        response = await self._request("GET", path)
        status = response.status_code
        if status != 200:
            await response.aclose()
            raise WebDavError("Could not download the backup from WebDAV.")
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > _MAX_RESPONSE_BYTES:
                await response.aclose()
                raise WebDavError("Remote backup is too large.")
            chunks.append(chunk)
        await response.aclose()
        return b"".join(chunks)

    async def download_to(self, path: str, dest) -> int:
        """Stream a remote object straight to a local file, returning its size.

        AUDIT-037: remote restore must be able to accept archives as large as
        the ones Lumi itself can create. ``get`` holds everything in memory
        under a small bound; this streams to disk bounded by the SAME
        ``MAX_TOTAL_BYTES`` used when building a backup, keeping the creation
        and restore-acceptance limits internally consistent.

        Path-traversal hardening: the caller derives ``dest`` from remote
        listing names (attacker = hostile WebDAV server). ``..`` segments are
        rejected, the parent is canonicalized via ``resolve()``, and the file
        is opened via ``dir_fd`` on that opened parent directory — so the
        kernel itself confines the write to the staging directory even if a
        name carries separators. Downloads land flat with 0600 (sensitive).
        """
        from lumirss.backup import MAX_TOTAL_BYTES

        dest_path = Path(dest)
        if ".." in dest_path.parts:
            raise WebDavError("Invalid download destination.")
        parent = dest_path.parent.resolve()
        response = await self._request("GET", path)
        status = response.status_code
        if status != 200:
            await response.aclose()
            raise WebDavError("Could not download the backup from WebDAV.")
        total = 0
        try:
            parent_fd = os.open(str(parent), os.O_RDONLY | os.O_DIRECTORY)
            try:
                fd = os.open(
                    dest_path.name,
                    os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                    0o600,
                    dir_fd=parent_fd,
                )
            finally:
                os.close(parent_fd)
            with os.fdopen(fd, "wb") as handle:
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_TOTAL_BYTES:
                        raise WebDavError("Remote backup is too large.")
                    handle.write(chunk)
        finally:
            await response.aclose()
        return total

    async def list_dir(self, path: str) -> list[dict[str, str]]:
        """PROPFIND depth 1; returns [{name, size}] for direct children."""
        body = (
            '<?xml version="1.0"?><d:propfind xmlns:d="DAV:">'
            "<d:prop><d:displayname/><d:getcontentlength/>"
            "<d:getlastmodified/></d:prop></d:propfind>"
        )
        response = await self._request(
            "PROPFIND",
            path,
            content=body.encode("utf-8"),
            headers={"Depth": "1", "Content-Type": "application/xml"},
        )
        if response.status_code == 401:
            await response.aclose()
            raise WebDavError("WebDAV rejected the credentials.")
        if response.status_code not in (200, 207):
            await response.aclose()
            raise WebDavError("WebDAV listing failed.")
        # PROPFIND 响应同样有界（与 GET 的 _MAX_RESPONSE_BYTES 一致）。
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > _MAX_LIST_BYTES:
                await response.aclose()
                raise WebDavError("WebDAV listing is too large.")
            chunks.append(chunk)
        await response.aclose()
        raw = b"".join(chunks)
        try:
            root = ElementTree.fromstring(raw)
        except Exception:
            raise WebDavError("WebDAV returned an unexpected response.") from None
        entries: list[dict[str, str]] = []
        seen = set()
        for response_el in root.findall(".//{DAV:}response"):
            href = response_el.findtext("{DAV:}href") or ""
            href = urllib.parse.unquote(href.strip())
            name = href.rstrip("/").split("/")[-1] if href else ""
            if not name or name in seen:
                continue
            seen.add(name)
            size_el = response_el.find(".//{DAV:}getcontentlength")
            size = size_el.text if size_el is not None and size_el.text else "0"
            entries.append({"name": name, "size": size})
        return entries

    async def delete(self, path: str) -> None:
        response = await self._request("DELETE", path)
        status = response.status_code
        await response.aclose()
        if status not in (200, 204, 404):
            raise WebDavError("Could not delete the remote backup.")
