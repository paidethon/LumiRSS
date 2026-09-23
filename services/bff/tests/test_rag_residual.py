"""P20 adversarial boundary tests: RAG residual/ghost content.

Audit gap: no end-to-end "delete entry → search/index returns nothing"
residual assertion. Two scenarios over the REAL RagService pipeline
(fake deterministic embedder — no fastembed download):

1. Delete via the REAL store deletion path (LibraryStore soft-delete and
   SearchEntryWriter.delete_entry — the paths whose projection-row
   removal is what the orphan sweep consumes), then run the SAME
   convergence function the background loop uses (``rag_index_pass``):
   the deleted refs must vanish from search, rag_chunks and rag_vec.
   The residual window BEFORE the sweep is asserted honestly too — it
   documents exactly the race the sweep exists to close.

2. A source deleted MID-index (after its page was staged, before the
   swap): a search executed AFTER deletion+swap must return NO ghost
   hits — the swap must not resurrect staged rows whose source row is
   already gone.
"""

import asyncio

import pytest

import lumirss.rag as rag_module
from lumirss.library import LibraryStore
from lumirss.rag import MODEL_DIM, RagService, rag_index_pass
from lumirss.search_library import LibrarySearchWriter
from lumirss.search_writer import SearchEntryWriter
from lumirss.storage import Database

TOKEN_A = "残留检索令牌AlphaQZ"
TOKEN_B = "残留检索令牌BetaQW"


def _run(coroutine):
    return asyncio.run(coroutine)


def install_fake_embedder(service: RagService) -> None:
    async def fake_embed(texts):
        vectors = []
        for text in texts:
            vector = [0.0] * MODEL_DIM
            vector[len(text) % MODEL_DIM] = 1.0
            vectors.append(vector)
        return vectors

    service._embedder.embed = fake_embed  # noqa: SLF001 — test seam


@pytest.fixture()
def rag_env(tmp_path, monkeypatch):
    """Hermetic RAG: the enable gate passes (flag patched) but the real
    embedder is replaced — nothing is downloaded, vec tables are real."""
    monkeypatch.setattr(rag_module, "_FASTEMBED_AVAILABLE", True)
    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    library = LibraryStore(db)
    service = RagService(db)
    install_fake_embedder(service)
    _run(service.enable())
    return {
        "db": db,
        "library": library,
        "service": service,
        "entries": SearchEntryWriter(db),
        "library_search": LibrarySearchWriter(db),
    }


def _refs_of(result) -> set[str]:
    return {item["ref"] for item in result["items"]}


def _chunk_rows(db: Database, ref: str) -> int:
    rows = _run(
        db.fetch_all("SELECT COUNT(*) AS n FROM rag_chunks WHERE ref = ?", (ref,))
    )
    return int(rows[0]["n"])


# -- (1) real deletion path → orphan sweep → zero residual --------------------


def test_deleted_sources_leave_no_residual_after_orphan_sweep(rag_env):
    env = rag_env
    service: RagService = env["service"]
    bookmark, _created = _run(
        env["library"].create_url_bookmark(
            "https://example.com/alpha", "Alpha 书签", f"正文含 {TOKEN_A} 标记。"
        )
    )
    _run(
        env["entries"].insert_entry(
            item_id="item-beta-1",
            entry_ref="rss:e1.residualbeta",
            feed_url="https://example.com/feed.xml",
            feed_title="Beta 源",
            title="Beta 条目",
            author="",
            url="https://example.com/beta",
            content_text=f"正文含 {TOKEN_B} 标记。",
            published_at="2026-01-01T00:00:00+00:00",
            read=0,
            starred=0,
            fetched_at=0,
        )
    )
    rss_ref = "rss:e1.residualbeta"

    report = _run(service.rebuild())
    assert report["status"] == "done"
    assert bookmark.ref in _refs_of(_run(service.search(TOKEN_A)))
    assert rss_ref in _refs_of(_run(service.search(TOKEN_B)))
    status = _run(service.status())
    assert status["vecRows"] == status["chunks"]
    assert status["chunks"] >= 2

    # Real deletion paths: library soft-delete + entry projection delete
    # (the projection-row removals the orphan sweep consumes). The route
    # layer's best-effort mark_stale is deliberately NOT invoked — this
    # is exactly the case (skipped/deferred invalidation) the sweep
    # exists to converge.
    assert _run(env["library"].delete_bookmark(bookmark.ref.split(":", 1)[1])) is True
    _run(env["entries"].delete_entry("item-beta-1"))

    # Honest residual window: the index still serves the deleted content
    # until convergence runs — the pre-condition the sweep must close.
    assert bookmark.ref in _refs_of(_run(service.search(TOKEN_A)))
    assert rss_ref in _refs_of(_run(service.search(TOKEN_B)))

    report = _run(rag_index_pass(service))
    assert report["swept"] == 2
    assert report["indexed"] == 0

    # Post-sweep: nothing residual anywhere.
    assert bookmark.ref not in _refs_of(_run(service.search(TOKEN_A)))
    assert rss_ref not in _refs_of(_run(service.search(TOKEN_B)))
    assert _chunk_rows(env["db"], bookmark.ref) == 0
    assert _chunk_rows(env["db"], rss_ref) == 0
    status = _run(service.status())
    assert status["chunks"] == 0
    assert status["vecRows"] == status["chunks"]


# -- (2) mid-index deletion → no ghost hits after deletion+swap ---------------


def test_source_deleted_mid_index_no_ghost_hits_after_swap(rag_env):
    """The F093 recheck catches sources deleted BEFORE their page is
    staged. This pins the OTHER window: deleted AFTER staging, BEFORE
    the swap — a search right after deletion+swap must not resurrect
    the staged rows (ghost hits)."""
    env = rag_env
    service: RagService = env["service"]
    library = env["library"]
    docs: list[tuple[str, str, str]] = []  # (ref, key, token)
    for index in range(20):
        view, _created = _run(
            library.create_url_bookmark(
                f"https://example.com/ghost-{index:02d}",
                f"幽灵文档{index:02d}",
                f"内容含 幽灵令牌{index:02d}QZ 标记，用于删除窗口测试。",
            )
        )
        docs.append((view.ref, f"ghost-{index:02d}", f"幽灵令牌{index:02d}QZ"))
    # The corpus is paged ordered by ref (_DOC_PAGE=16): the smallest-ref
    # doc is in page 1, so it is STAGED before page 2 is ever rechecked.
    ghost_ref, _ghost_key, ghost_token = min(docs)
    survivor_ref, _survivor_key, survivor_token = max(docs)

    original_present = service._refs_still_present  # noqa: SLF001
    deleted = {"flag": False}

    async def present_with_mid_delete(docs_page):
        present, skipped = await original_present(docs_page)
        if not deleted["flag"] and all(doc["ref"] != ghost_ref for doc in docs_page):
            # First page WITHOUT the ghost → the ghost's page (page 1) is
            # fully staged; delete it via the real store path now — after
            # staging, BEFORE the swap.
            deleted["flag"] = True
            assert (
                await env["library"].delete_bookmark(ghost_ref.split(":", 1)[1])
                is True
            )
        return present, skipped

    service._refs_still_present = present_with_mid_delete  # noqa: SLF001
    report = _run(service.rebuild())
    assert report["status"] == "done"
    assert deleted["flag"] is True

    # The deletion was NOT caught by the F093 recheck (the ghost passed
    # it) — the swap itself must be the boundary that refuses ghosts.
    job = _run(service._job_latest())  # noqa: SLF001
    assert ghost_ref not in (job["stats"] or {}).get("skipped", [])

    result = _run(service.search(ghost_token))
    assert ghost_ref not in _refs_of(result), (
        "ghost hit: a source deleted mid-index must not be searchable "
        "after the swap"
    )
    assert _chunk_rows(env["db"], ghost_ref) == 0

    # Sanity: surviving docs stay searchable and vec stays consistent.
    assert survivor_ref in _refs_of(_run(service.search(survivor_token)))
    status = _run(service.status())
    assert status["vecRows"] == status["chunks"]
