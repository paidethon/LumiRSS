"""0021 hardening: global request-body ceiling.

The middleware rejects bodies above MAX_REQUEST_BODY_BYTES with a stable
413 envelope — both when Content-Length announces the size up front and
when a chunked body streams past the cap. Route-level bounds stay
authoritative below the ceiling (OPML keeps its own 2 MiB error type).
"""

import asyncio

from fastapi.testclient import TestClient

from lumirss.main import MAX_REQUEST_BODY_BYTES, app

ENVELOPE_TYPE = "request_too_large"


def run(coroutine):
    return asyncio.run(coroutine)


def test_oversized_content_length_is_rejected_before_validation():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/opml/import/preview",
            content=b"x" * (MAX_REQUEST_BODY_BYTES + 1),
            headers={"Content-Type": "text/xml"},
        )
    assert response.status_code == 413
    assert response.json()["error"]["type"] == ENVELOPE_TYPE


def test_oversized_json_body_is_rejected_stably():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/backups",
            content=b'{"target":"' + b"l" * (MAX_REQUEST_BODY_BYTES + 1) + b'"}',
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 413
    assert response.json()["error"]["type"] == ENVELOPE_TYPE


def test_chunked_body_streaming_guard():
    """No Content-Length header: the streamed receive guard still stops
    the body past the cap (raw ASGI call to control the framing)."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "POST",
        "path": "/api/v1/opml/import/preview",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"text/xml"), (b"transfer-encoding", b"chunked")],
        "server": ("testserver", 80),
        "client": ("testclient", 123),
        "scheme": "http",
        "http_version": "1.1",
    }
    big = b"y" * (MAX_REQUEST_BODY_BYTES + 1)
    messages = [
        {"type": "http.request", "body": big, "more_body": False},
    ]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    run(app(scope, receive, send))

    starts = [m for m in sent if m["type"] == "http.response.start"]
    assert starts and starts[0]["status"] == 413
    bodies = [m for m in sent if m["type"] == "http.response.body"]
    assert ENVELOPE_TYPE.encode() in b"".join(m["body"] for m in bodies)


def test_normal_requests_pass_through_untouched(tmp_path):
    """Below the ceiling nothing changes: a small valid POST still works."""
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/opml/import/preview",
            content=b"<?xml version='1.0'?><opml version='2.0'><body/></opml>",
            headers={"Content-Type": "text/xml"},
        )
    assert response.status_code in (200, 400)  # parsed, not size-rejected
    assert response.json().get("error", {}).get("type") != ENVELOPE_TYPE
