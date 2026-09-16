"""X-Request-ID correlation middleware（pool #47）。

每个响应（含错误信封）携带 X-Request-ID；入参安全则回显，否则生成；
不安全/超长的入参被替换（header 与日志注入防护）。"""

import re

from fastapi.testclient import TestClient

from lumirss.main import app

_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def test_response_carries_generated_request_id(client):
    response = client.get("/api/v1/version")
    assert response.status_code == 200
    rid = response.headers.get("x-request-id")
    assert rid is not None
    assert _HEX32.match(rid)


def test_safe_inbound_request_id_is_echoed(client):
    response = client.get(
        "/api/v1/version", headers={"X-Request-ID": "my-op-20260917_1.a"}
    )
    assert response.headers.get("x-request-id") == "my-op-20260917_1.a"


def test_unsafe_inbound_request_id_is_replaced_not_echoed(client):
    response = client.get(
        "/api/v1/version",
        headers={"X-Request-ID": "bad id\ninjection\rX-Evil: 1"},
    )
    rid = response.headers.get("x-request-id")
    assert rid is not None
    assert rid != "bad id\ninjection\rX-Evil: 1"
    assert _HEX32.match(rid)


def test_oversized_inbound_request_id_is_replaced(client):
    response = client.get(
        "/api/v1/version", headers={"X-Request-ID": "x" * 500}
    )
    rid = response.headers.get("x-request-id")
    assert rid is not None
    assert len(rid) == 32


def test_error_envelopes_carry_request_id_too(client):
    response = client.get("/api/v1/search", params={"q": "   "})
    assert response.status_code == 400
    assert response.headers.get("x-request-id") is not None


def test_current_request_id_available_in_handler(client):
    from lumirss.middleware import current_request_id

    seen: list[str | None] = []

    @app.get("/api/v1/__test_request_id")
    async def _probe() -> dict:
        seen.append(current_request_id())
        return {"ok": True}

    with TestClient(app) as c:
        c.get("/api/v1/__test_request_id")
    assert seen and seen[0] is not None
