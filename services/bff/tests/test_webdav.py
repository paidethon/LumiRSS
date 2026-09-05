"""Tests for the server-side WebDAV client (0018).

Uses httpx.MockTransport — never a real network. Covers URL policy, auth,
bounded operations, redirect policy, unexpected XML and redaction.
"""

import asyncio

import httpx
import pytest

from lumirss.webdav import (
    WebDavClient,
    WebDavError,
    WebDavInvalidSettings,
    WebDavSettings,
    backup_root_path,
    normalize_remote_dir,
    normalize_server_url,
)


def run(coroutine):
    return asyncio.run(coroutine)


def _client(handler):
    settings = WebDavSettings(
        server_url="https://dav.example.com",
        username="alice",
        remote_dir="",
        tls_verify=True,
    )
    return WebDavClient(settings, "secret-password", transport=httpx.MockTransport(handler))


def test_normalize_rejects_credentials_in_url():
    with pytest.raises(WebDavError):
        normalize_server_url("https://user:pass@dav.example.com")


def test_invalid_settings_are_specific_client_error_type():
    """AUDIT: structural client-input failures raise the specific
    WebDavInvalidSettings (mapped to 400), which is still a WebDavError so
    existing expectations hold."""
    assert issubclass(WebDavInvalidSettings, WebDavError)
    with pytest.raises(WebDavInvalidSettings):
        normalize_server_url("")
    with pytest.raises(WebDavInvalidSettings):
        normalize_server_url("ftp://dav.example.com")
    with pytest.raises(WebDavInvalidSettings):
        normalize_server_url("https://user:pass@dav.example.com")
    with pytest.raises(WebDavInvalidSettings):
        normalize_remote_dir("/a/../../etc")


def test_normalize_rejects_public_http():
    with pytest.raises(WebDavError):
        normalize_server_url("http://dav.example.com")


def test_normalize_allows_private_http():
    assert normalize_server_url("http://192.168.1.10") == "http://192.168.1.10"


def test_normalize_allows_https():
    assert normalize_server_url("https://dav.example.com/") == "https://dav.example.com"


def test_remote_dir_rejects_traversal():
    with pytest.raises(WebDavError):
        normalize_remote_dir("/backups/../../etc")


def test_remote_dir_normalizes():
    assert normalize_remote_dir("/backups/") == "/backups"


def test_put_ok():
    calls = {}

    def handler(request):
        calls["auth"] = request.headers.get("Authorization")
        calls["method"] = request.method
        return httpx.Response(201)

    client = _client(handler)
    run(client.put("/LumiRSS/backups/2026/09/x.backup", b"data"))
    assert calls["method"] == "PUT"
    assert "Basic" in calls["auth"]


def test_auth_failure_is_safe_error():
    def handler(request):
        return httpx.Response(401)

    client = _client(handler)
    with pytest.raises(WebDavError) as exc:
        run(client.list_dir("/LumiRSS/backups"))
    assert "credential" in str(exc.value).lower()


def test_connection_error_is_safe():
    def handler(request):
        raise httpx.ConnectError("dial tcp boom")

    client = _client(handler)
    with pytest.raises(WebDavError) as exc:
        run(client.get("/x"))
    assert "boom" not in str(exc.value)


def test_redirect_outside_origin_rejected():
    def handler(request):
        if request.url.host == "dav.example.com":
            return httpx.Response(302, headers={"Location": "https://evil.example.com/x"})
        return httpx.Response(200)

    client = _client(handler)
    with pytest.raises(WebDavError):
        run(client.get("/x"))


def test_propfind_parses_entries():
    xml = (
        '<?xml version="1.0"?>'
        '<d:multistatus xmlns:d="DAV:">'
        '<d:response><d:href>/LumiRSS/backups/a.backup</d:href>'
        '<d:propstat><d:prop><d:getcontentlength>100</d:getcontentlength>'
        "</d:prop></d:propstat></d:response>"
        '<d:response><d:href>/LumiRSS/backups/b.backup</d:href>'
        '<d:propstat><d:prop><d:getcontentlength>200</d:getcontentlength>'
        "</d:prop></d:propstat></d:response>"
        "</d:multistatus>"
    )

    def handler(request):
        assert request.method == "PROPFIND"
        return httpx.Response(207, content=xml)

    client = _client(handler)
    entries = run(client.list_dir("/LumiRSS/backups"))
    assert {e["name"] for e in entries} == {"a.backup", "b.backup"}


def test_unexpected_xml_is_safe():
    def handler(request):
        return httpx.Response(207, content="this is not xml <<<")

    client = _client(handler)
    with pytest.raises(WebDavError):
        run(client.list_dir("/LumiRSS/backups"))


def test_get_bounded_response():
    def handler(request):
        return httpx.Response(200, content=b"x" * 1000)

    client = _client(handler)
    data = run(client.get("/x.backup"))
    assert len(data) == 1000


def test_backup_root_path():
    assert backup_root_path("") == "/LumiRSS/backups"
    assert backup_root_path("/dav") == "/dav/LumiRSS/backups"


def test_download_to_streams_to_file(tmp_path):
    """AUDIT-037: remote restore streams to disk (not into a small in-RAM cap)."""

    def handler(request):
        return httpx.Response(200, content=b"y" * 5000)

    client = _client(handler)
    dest = tmp_path / "out.backup"
    total = run(client.download_to("/x.backup", dest))
    assert total == 5000
    assert dest.read_bytes() == b"y" * 5000


def test_download_to_rejects_traversal_destination(tmp_path):
    """Defense-in-depth: a `..` destination (e.g. derived from a hostile
    WebDAV listing name) is rejected before any byte is written."""

    def handler(request):
        return httpx.Response(200, content=b"y" * 10)

    client = _client(handler)
    escaped = tmp_path / "sub" / ".." / ".." / "evil.backup"
    with pytest.raises(WebDavError):
        run(client.download_to("/x.backup", escaped))
    assert not (tmp_path / "evil.backup").exists()


def test_download_to_connection_error_is_safe(tmp_path):
    def handler(request):
        raise httpx.ConnectError("dial tcp boom")

    client = _client(handler)
    with pytest.raises(WebDavError) as exc:
        run(client.download_to("/x.backup", tmp_path / "out.backup"))
    assert "boom" not in str(exc.value)
