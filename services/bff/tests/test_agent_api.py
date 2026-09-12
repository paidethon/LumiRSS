"""Agent workbench HTTP-level tests (P0-08): run lifecycle over the real
routes — 404 thread_not_found, 409 pending_approval, 409 no_active_run,
provider-unavailable terminal state, SSE replay, resolved citation
details and the fresh-app obsidian tool regression (P0-08f)."""

import asyncio
import time

import pytest

from lumirss.agent_store import AgentStore
from lumirss.library import LibraryStore
from lumirss.main import app


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture()
def agent_env(client):  # noqa: F811 — reuse the conftest fixture
    """Fresh agent wiring per test: a new store + loop over the temp db
    (cached services reset to force a fresh build, like a new process)."""
    app.state.agent_store = None
    app.state.agent_loop = None
    yield {"db": app.state.db}
    # Drain background turn tasks BEFORE the temp dir is deleted — a task
    # hitting a removed database file would fail noisily in a later test.
    deadline = time.time() + 5
    while app.state.agent_tasks and time.time() < deadline:
        time.sleep(0.05)


def _create_thread(client) -> str:
    response = client.post("/api/v1/agent/threads")
    assert response.status_code == 201
    return response.json()["id"]


def test_post_message_on_missing_thread_is_404(agent_env, client):
    response = client.post(
        "/api/v1/agent/threads/nope/messages", json={"text": "你好"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "thread_not_found"


def test_post_message_without_provider_persists_honest_failure(agent_env, client):
    thread_id = _create_thread(client)
    response = client.post(
        f"/api/v1/agent/threads/{thread_id}/messages", json={"text": "你好"}
    )
    assert response.status_code == 202
    assert response.json()["status"] == "processing"
    # The background turn finishes with an honest assistant message and
    # the run marker is cleared (never stuck processing).
    deadline = time.time() + 5
    while time.time() < deadline:
        messages = client.get(
            f"/api/v1/agent/threads/{thread_id}/messages"
        ).json()["items"]
        roles = [m["role"] for m in messages]
        if roles and roles[-1] == "assistant":
            break
        time.sleep(0.05)
    assert messages[-1]["content"]["text"].startswith("AI 未配置")
    store = AgentStore(app.state.db)
    assert run(store.is_running(thread_id)) is False


def test_new_message_while_approval_pending_is_409(agent_env, client):
    store = AgentStore(app.state.db)
    thread_id = _create_thread(client)
    run(
        store.create_approval(
            thread_id, "call-1", "save_bookmark",
            {"url": "https://example.com/x", "title": "x"},
        )
    )
    response = client.post(
        f"/api/v1/agent/threads/{thread_id}/messages", json={"text": "继续聊"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["type"] == "pending_approval"


def test_cancel_without_run_is_409(agent_env, client):
    thread_id = _create_thread(client)
    response = client.post(f"/api/v1/agent/threads/{thread_id}/cancel")
    assert response.status_code == 409
    assert response.json()["error"]["type"] == "no_active_run"


def test_fresh_app_registry_has_obsidian_and_workspace_tools(agent_env, client):
    """P0-08f regression: a fresh loop build (no obsidian route touched)
    registers the obsidian read tool and the workspace list tool."""
    thread_id = _create_thread(client)  # any agent route builds the loop
    client.post(
        f"/api/v1/agent/threads/{thread_id}/messages", json={"text": "hi"}
    )
    loop = app.state.agent_loop
    assert loop is not None
    names = loop.tool_names()
    assert "list_notes" in names
    assert "list_workspace_items" in names


def test_messages_carry_resolved_citation_details(agent_env, client):
    store = AgentStore(app.state.db)
    thread_id = _create_thread(client)
    library = LibraryStore(app.state.db)
    view, _created = run(
        library.create_url_bookmark("https://example.com/cited", "被引用的书签")
    )
    run(
        store.append_message(
            thread_id,
            role="assistant",
            content={"text": "依据如下。"},
            citations=[view.ref],
        )
    )
    response = client.get(f"/api/v1/agent/threads/{thread_id}/messages")
    assert response.status_code == 200
    body = response.json()
    assert body["items"][-1]["citations"] == [view.ref]
    details = body["citationDetails"]
    assert details, "citation refs must arrive resolved"
    target = next(d for d in details if d["ref"] == view.ref)
    assert target["title"] == "被引用的书签"
    assert target["domain"] == "library"
    assert target["stale"] is False
    assert target["payload"].get("itemType")


def test_sse_replays_then_closes_when_idle(agent_env, client):
    store = AgentStore(app.state.db)
    thread_id = _create_thread(client)
    run(store.append_message(thread_id, role="user", content={"text": "在吗"}))
    with client.stream(
        "GET", f"/api/v1/agent/threads/{thread_id}/events"
    ) as response:
        assert response.status_code == 200
        events = []
        for line in response.iter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            if events and events[-1] == "done":
                break
    assert events[0] == "message"
    assert events[-1] == "done"
