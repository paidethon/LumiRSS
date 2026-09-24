"""E04 contract tests: agent/rag endpoints previously returned bare
dicts, so the OpenAPI schema (and the generated web types) degraded to
``{}``. These tests pin the repaired contract from both sides:

1. every agent/rag route documents a real success schema in OpenAPI
   (``$ref`` to the response model, or the honest SSE/markdown media
   types for the two streaming/file endpoints);
2. live responses parse back through the same Pydantic models that
   generated the schema — a model/wire mismatch now fails loudly here
   instead of drifting silently.
"""

import asyncio
import time

import pytest
from fastapi.routing import APIRoute

from lumirss.main import app
from lumirss.models import (
    AgentMessageListResponse,
    AgentThreadSettings,
    AgentTurnAccepted,
    RagRebuildPauseResult,
    RagStatus,
)

# E04 之前 OpenAPI 里 200 content 是空 ``{}`` 的端点 → 修复后必须引用
# 具名响应模型（顺序：method, path, schema 名）。
_REPAIRED_ENDPOINTS = [
    ("GET", "/api/v1/agent/threads/{thread_id}/messages", "AgentMessageListResponse"),
    ("POST", "/api/v1/agent/threads/{thread_id}/messages", "AgentTurnAccepted"),
    ("POST", "/api/v1/agent/threads/{thread_id}/approvals", "AgentApprovalResult"),
    ("POST", "/api/v1/agent/threads/{thread_id}/cancel", "AgentCancelResult"),
    ("GET", "/api/v1/agent/threads/search", "AgentThreadSearchResponse"),
    ("PATCH", "/api/v1/agent/threads/{thread_id}", "AgentThreadSettings"),
    ("POST", "/api/v1/agent/threads/{thread_id}/branch", "AgentBranchResult"),
    (
        "POST",
        "/api/v1/agent/threads/{thread_id}/approvals/{approval_id}/preview",
        "AgentApprovalPreview",
    ),
    ("GET", "/api/v1/rag/status", "RagStatus"),
    ("POST", "/api/v1/rag/rebuild/pause", "RagRebuildPauseResult"),
]


def _openapi_operation(method: str, path: str) -> dict:
    schema = app.openapi()
    operation = schema["paths"][path][method.lower()]
    return operation


def test_openapi_pins_agent_and_rag_response_schemas():
    """Every repaired endpoint documents its named response model."""
    for method, path, schema_name in _REPAIRED_ENDPOINTS:
        operation = _openapi_operation(method, path)
        success_code = (
            "202"
            if (method, path) == ("POST", "/api/v1/agent/threads/{thread_id}/messages")
            else "200"
        )
        content = operation["responses"][success_code]["content"]
        assert "application/json" in content, (method, path)
        assert (
            content["application/json"]["schema"]["$ref"]
            == f"#/components/schemas/{schema_name}"
        ), (method, path)


def test_openapi_documents_sse_and_markdown_media_types():
    """SSE stream and export document their real media types (not an
    empty JSON schema) — the two endpoints that cannot carry a
    response_model."""
    sse = _openapi_operation(
        "GET", "/api/v1/agent/threads/{thread_id}/events"
    )["responses"]["200"]["content"]
    assert set(sse) == {"text/event-stream"}
    assert sse["text/event-stream"]["schema"]["type"] == "string"

    export = _openapi_operation(
        "GET", "/api/v1/agent/threads/{thread_id}/export"
    )["responses"]["200"]["content"]
    assert set(export) == {"text/markdown; charset=utf-8"}
    assert export["text/markdown; charset=utf-8"]["schema"]["type"] == "string"


def test_no_agent_rag_route_left_with_empty_success_schema():
    """Sweep guard: no agent/rag JSON route may regress to an empty
    (``{}``) success schema, and DELETE stays honestly 204-no-content."""
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.path.startswith(("/api/v1/agent/", "/api/v1/rag/")):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            operation = _openapi_operation(method.lower(), route.path)
            responses = operation["responses"]
            if method == "DELETE":
                assert "204" in responses
                assert "content" not in responses["204"]
                continue
            success = next(
                (code for code in ("200", "201", "202") if code in responses),
                None,
            )
            assert success is not None, (method, route.path)
            content = responses[success].get("content") or {}
            assert content, (method, route.path)
            for media_type, media in content.items():
                if media_type == "application/json":
                    schema = media.get("schema") or {}
                    assert schema, (method, route.path)


@pytest.fixture()
def agent_env(client):  # noqa: F811 — reuse the conftest fixture
    """Fresh agent wiring per test (same protocol as test_agent_api)."""
    from lumirss.main import app

    app.state.agent_store = None
    app.state.agent_loop = None
    yield {"db": app.state.db}
    deadline = time.time() + 15
    while app.state.agent_tasks and time.time() < deadline:
        time.sleep(0.05)
    for task in tuple(app.state.agent_tasks):
        task.cancel()


def _seed_messages(client, thread_id: str) -> None:
    """Seed one message per content variant through the real store."""
    from lumirss.agent_store import AgentStore
    from lumirss.main import app

    store = AgentStore(app.state.db)

    async def seed():
        await store.append_message(
            thread_id, role="user", content={"text": "你好"}
        )
        await store.append_message(
            thread_id,
            role="assistant",
            content={
                "text": "",
                "toolCalls": [
                    {"callId": "c1", "name": "add_tag", "argumentsText": "{}"}
                ],
            },
        )
        await store.append_message(
            thread_id,
            role="tool",
            content={
                "callId": "c1",
                "name": "add_tag",
                "result": {"untrusted": True, "payload": {"ok": True}},
            },
            citations=["library:x/1"],
        )
        await store.append_message(
            thread_id,
            role="approval",
            content={
                "approvalId": "a1",
                "threadId": thread_id,
                "callId": "c1",
                "tool": "add_tag",
                "args": {"itemRef": "library:x/1"},
                "status": "pending",
                "expiresInMinutes": 15,
            },
        )

    asyncio.run(seed())


def test_messages_response_parses_into_agent_message_list_response(
    agent_env, client
):
    """GET /messages → the wire body must validate against the very
    model that documents it (all four role/content variants)."""
    thread_id = client.post("/api/v1/agent/threads").json()["id"]
    _seed_messages(client, thread_id)

    response = client.get(f"/api/v1/agent/threads/{thread_id}/messages")
    assert response.status_code == 200
    parsed = AgentMessageListResponse.model_validate(response.json())

    assert [m.role for m in parsed.items] == [
        "user",
        "assistant",
        "tool",
        "approval",
    ]
    # user content stays wire-exact (no invented keys)
    assert parsed.items[0].content.model_dump() == {"text": "你好"}
    # tool result keeps the untrusted envelope; citations resolve through
    # the message row
    assert parsed.items[2].content.result is not None
    assert parsed.items[2].content.result.untrusted is True
    assert parsed.items[2].citations == ["library:x/1"]
    assert parsed.items[3].content.approvalId == "a1"


def test_turn_accept_and_thread_settings_parse(agent_env, client):
    """202 body parses as AgentTurnAccepted; PATCH settings parses as
    AgentThreadSettings with the exact sparse scope shapes."""
    thread_id = client.post("/api/v1/agent/threads").json()["id"]

    queued = client.post(
        f"/api/v1/agent/threads/{thread_id}/messages", json={"text": "在吗"}
    )
    assert queued.status_code == 202
    accepted = AgentTurnAccepted.model_validate(queued.json())
    assert accepted.status == "processing"

    scope_patch = client.patch(
        f"/api/v1/agent/threads/{thread_id}",
        json={"scope": {"entryRefs": ["library:x/1"]}},
    )
    assert scope_patch.status_code == 200
    settings = AgentThreadSettings.model_validate(scope_patch.json())
    # scope is the exact single-key variant, never null-padded
    assert scope_patch.json()["scope"] == {"entryRefs": ["library:x/1"]}
    assert settings.scope is not None
    assert settings.scope.entryRefs == ["library:x/1"]

    cleared = client.patch(
        f"/api/v1/agent/threads/{thread_id}",
        json={"clearScope": True},
    )
    assert cleared.status_code == 200
    assert cleared.json()["scope"] is None  # explicit null, not omitted


def test_rag_status_and_pause_parse(client):
    """GET /rag/status parses as RagStatus (job section present even
    without a job); POST /rag/rebuild/pause parses as
    RagRebuildPauseResult."""
    response = client.get("/api/v1/rag/status")
    assert response.status_code == 200
    body = response.json()
    assert "job" in body  # 无作业 → 显式 null，键不消失
    status = RagStatus.model_validate(body)
    assert status.enabled is False
    assert status.job is None

    paused = client.post("/api/v1/rag/rebuild/pause")
    assert paused.status_code == 200
    result = RagRebuildPauseResult.model_validate(paused.json())
    assert result.paused is False
    assert result.jobId is None
