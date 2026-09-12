"""RAG HTTP-level tests (P0-07c): /api/v1/rag/* envelopes.

The audit found ZERO HTTP-level tests for these routes; enable/rebuild/
search/status/disable are covered here against a temp database with a
deterministic fake embedder (no downloads).
"""

import asyncio

import pytest

from lumirss.main import app
from lumirss.rag import MODEL_DIM, RagService
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database

_REF = "library:0b8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f"


def _fake_embedder(service: RagService) -> None:
    async def fake_embed(texts):
        vectors = []
        for text in texts:
            vector = [0.0] * MODEL_DIM
            vector[len(text) % MODEL_DIM] = 1.0
            vectors.append(vector)
        return vectors

    service._embedder.embed = fake_embed  # noqa: SLF001 — test seam


@pytest.fixture()
def client(client):  # noqa: F811 — reuse the conftest fixture
    yield client


def test_status_reports_resource_state(client):
    response = client.get("/api/v1/rag/status")
    assert response.status_code == 200
    body = response.json()
    for key in (
        "enabled", "chunks", "model", "dim", "vecTable", "vecRows",
        "modelLoaded", "lastRebuildAt", "lastError", "fastembedAvailable",
    ):
        assert key in body
    assert body["enabled"] is False
    assert body["chunks"] == 0
    assert body["modelLoaded"] is False


def test_enable_without_fastembed_is_honest_503(client, monkeypatch):
    import lumirss.rag as rag_module

    monkeypatch.setattr(rag_module, "_FASTEMBED_AVAILABLE", False)
    response = client.post("/api/v1/rag/enable")
    assert response.status_code == 503
    assert response.json()["error"]["type"] == "model_unavailable"
    # The failure is visible in status for the UI.
    status = client.get("/api/v1/rag/status").json()
    assert status["enabled"] is False
    assert status["lastError"]


def test_rebuild_and_search_over_http(client):
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db = Database(f"{tmp}/lumi.sqlite")

        async def seed():
            await db.migrate()
            writer = LibrarySearchWriter(db)
            await writer.upsert(
                ref=_REF,
                kind="clip",
                title="vLLM 量化部署",
                body="vLLM 量化推理的部署记录，量化参数与显存占用。",
                url=None,
            )

        asyncio.run(seed())
        service = RagService(db)
        _fake_embedder(service)
        app.state.rag_service = service
        try:
            rebuilt = client.post("/api/v1/rag/rebuild")
            assert rebuilt.status_code == 200
            assert rebuilt.json()["chunks"] >= 1

            searched = client.get("/api/v1/rag/search", params={"q": "量化"})
            assert searched.status_code == 200
            body = searched.json()
            assert body["items"]
            assert body["items"][0]["ref"] == _REF
            assert body["semanticUsed"] is False  # never enabled → honest
            assert body["semanticError"]

            status = client.get("/api/v1/rag/status").json()
            assert status["chunks"] >= 1
            assert status["vecRows"] == status["chunks"]
        finally:
            app.state.rag_service = None


def test_disable_route_resets_enabled(client):
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db = Database(f"{tmp}/lumi.sqlite")
        service = RagService(db)
        _fake_embedder(service)
        app.state.rag_service = service
        try:
            enabled = client.post("/api/v1/rag/enable")
            assert enabled.status_code == 200
            assert enabled.json() == {"enabled": True}
            disabled = client.post("/api/v1/rag/disable")
            assert disabled.status_code == 200
            assert disabled.json() == {"enabled": False}
            assert client.get("/api/v1/rag/status").json()["enabled"] is False
        finally:
            app.state.rag_service = None
