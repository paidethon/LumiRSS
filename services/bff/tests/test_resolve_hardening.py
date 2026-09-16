"""Resolve fan-out hardening (pool #44/#13).

/resolve used to start one unbounded coroutine per ref (up to 100) with
no deadline and no exception isolation: one failing resolver 500ed the
whole batch, and every stale card looked identical. These tests pin: a
bounded concurrency semaphore, per-item failure isolation with
distinguishable stale reasons, and honest timeout/error cards instead of
silent fake successes.
"""

import asyncio
import uuid

import pytest

from lumirss.main import app
from lumirss.sources import ResolvedItem


def _library_ref() -> str:
    return f"library:{uuid.uuid4()}"


@pytest.fixture()
def registry(client):
    """The app-level Source Registry dict, built via one warm-up request."""
    response = client.post("/api/v1/resolve", json={"refs": [_library_ref()]})
    assert response.status_code == 200
    return app.state.source_registry


def _view(ref: str, title: str) -> ResolvedItem:
    return ResolvedItem(
        ref=ref, domain="library", kind="bookmark", title=title, source="t"
    )


def test_resolve_isolates_one_broken_ref(client, registry, monkeypatch):
    """One resolver blowing up must yield a stale card with reason
    'error' for that ref only — the rest of the batch stays intact."""

    async def boom(key):
        raise RuntimeError("resolver bug")

    monkeypatch.setitem(registry, "library", boom)
    broken_ref = _library_ref()
    response = client.post("/api/v1/resolve", json={"refs": [broken_ref]})
    assert response.status_code == 200, "one bad ref must not 500 the batch"
    item = response.json()["items"][0]
    assert item["stale"] is True
    assert item["staleReason"] == "error"
    assert item["ref"] == broken_ref


def test_unknown_domain_and_missing_content_are_distinguishable(
    client, registry, monkeypatch
):
    """Pool #13: 'domain not supported right now' and 'content gone'
    must not collapse into one generic 已丢失 state."""
    monkeypatch.setattr(app.state, "source_registry", {})
    response = client.post(
        "/api/v1/resolve", json={"refs": [_library_ref()]}
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["staleReason"] == "unsupported"

    # Restore the real registry: a well-formed ref whose content does
    # not exist resolves to not_found, a distinct state.
    monkeypatch.setattr(app.state, "source_registry", registry)
    response = client.post(
        "/api/v1/resolve", json={"refs": [_library_ref()]}
    )
    item = response.json()["items"][0]
    assert item["stale"] is True
    assert item["staleReason"] == "not_found"


def test_resolve_caps_concurrent_fanout(client, registry, monkeypatch):
    """100 refs against a slow resolver never runs more than the cap
    (16) upstream calls at once."""
    from lumirss.routers.workspaces import _RESOLVE_CONCURRENCY

    active = 0
    peak = 0

    async def slow(key):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return _view(f"library:{key}", key)

    monkeypatch.setitem(registry, "library", slow)
    refs = [_library_ref() for _ in range(100)]
    response = client.post("/api/v1/resolve", json={"refs": refs})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 100
    assert peak <= _RESOLVE_CONCURRENCY, (
        f"resolve fan-out peaked at {peak}, cap is {_RESOLVE_CONCURRENCY}"
    )


def test_resolve_timeout_becomes_distinct_stale_card(
    client, registry, monkeypatch
):
    """A resolver hanging past the deadline yields reason 'timeout', not
    a stuck request and not a generic error."""
    import lumirss.routers.workspaces as ws

    async def hang(key):
        await asyncio.sleep(5)
        raise AssertionError("should have been cancelled")

    monkeypatch.setattr(ws, "_RESOLVE_TIMEOUT_S", 0.05)
    monkeypatch.setitem(registry, "library", hang)
    response = client.post("/api/v1/resolve", json={"refs": [_library_ref()]})
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["stale"] is True
    assert item["staleReason"] == "timeout"
