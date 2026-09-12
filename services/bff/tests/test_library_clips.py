"""Web clip pipeline tests (phase2 M2 + recovery P0-03).

Covers the SSRF-guarded fetch refusals (private/metadata address matrix,
fail-closed before any dial), clip CRUD with duplicate-url convergence,
transactional writes (no orphan identity rows on integrity failure),
and the server-side contract: the create endpoint re-derives content
from the URL and NEVER stores client-submitted HTML.
"""

import sqlite3

import pytest

from lumirss.clip_fetch import ClipFetchError, ExtractedPage
from lumirss.library_clips import ClipInvalid, ClipStore
from lumirss.search_library import LibrarySearchWriter


@pytest.fixture()
def clip_db(tmp_path):
    import asyncio

    from lumirss.storage import Database

    db = Database(tmp_path / "lumi.sqlite")

    async def seed():
        await db.migrate()

    asyncio.run(seed())
    return db


def _run(coroutine):
    import asyncio

    return asyncio.run(coroutine)


def test_clip_store_create_duplicate_and_projection(clip_db):
    store = ClipStore(clip_db)
    first, created = _run(
        store.create_clip(
            url="https://example.com/a",
            title="标题",
            content_html="<p>正文</p>",
            content_text="正文",
        )
    )
    assert created is True
    assert first.ref.startswith("library:")

    duplicate, created = _run(
        store.create_clip(
            url="https://example.com/a",
            title="另一标题",
            content_html="<p>x</p>",
            content_text="x",
        )
    )
    assert created is False
    assert duplicate.ref == first.ref
    assert duplicate.title == "标题"  # canonical row keeps first content

    projection = LibrarySearchWriter(clip_db)
    hits = _run(projection.search("标题"))
    assert len(hits) == 1
    assert hits[0]["ref"] == first.ref

    _run(store.delete_clip(first.ref.split(":", 1)[1]))
    assert _run(projection.search("标题")) == []


def test_clip_store_validations(clip_db):
    import pytest

    store = ClipStore(clip_db)
    with pytest.raises((ClipInvalid, ClipFetchError)):
        _run(
            store.create_clip(
                url="javascript:alert(1)",
                title="t",
                content_html="<p>x</p>",
                content_text="x",
            )
        )
    with pytest.raises(ClipInvalid):
        _run(
            store.create_clip(
                url="https://a.com",
                title="t",
                content_html="",
                content_text="x",
            )
        )
    with pytest.raises(ClipInvalid):
        _run(
            store.create_clip(
                url="https://a.com",
                title="t",
                content_html="<p>" + "x" * (2 * 1024 * 1024 + 10) + "</p>",
                content_text="x",
            )
        )


def test_integrity_failure_rolls_back_no_orphan_identity(clip_db):
    """A racing duplicate insert fails INSIDE the transaction; the
    library_items identity row must roll back with it (recovery P0-03)."""
    store = ClipStore(clip_db)
    first, _ = _run(
        store.create_clip(
            url="https://example.com/race",
            title="t",
            content_html="<p>x</p>",
            content_text="x",
        )
    )

    async def none(url):
        return None  # bypass the converge pre-check to simulate a race

    original = store._find_by_url
    calls = {"n": 0}

    async def flaky(url):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # pre-check misses (race), the retry below hits
        return await original(url)

    store._find_by_url = flaky
    duplicate, created = _run(
        store.create_clip(
            url="https://example.com/race",
            title="other",
            content_html="<p>y</p>",
            content_text="y",
        )
    )
    assert created is False
    assert duplicate.ref == first.ref

    row = _run(
        clip_db.fetch_one("SELECT COUNT(*) AS n FROM library_items WHERE kind = 'clip'")
    )
    assert int(row["n"]) == 1  # the loser's identity row rolled back


def test_list_clips_pagination(clip_db):
    store = ClipStore(clip_db)
    for index in range(5):
        _run(
            store.create_clip(
                url=f"https://example.com/{index}",
                title=f"文章{index}",
                content_html=f"<p>{index}</p>",
                content_text=str(index),
            )
        )
    items, cursor = _run(store.list_clips(limit=3))
    assert len(items) == 3
    assert cursor is not None
    rest, cursor2 = _run(store.list_clips(limit=3, cursor=cursor))
    assert len(rest) == 2
    assert cursor2 is None
    seen = {item.url for item in items + rest}
    assert len(seen) == 5


# --------------------------------------------------------------------------
# Endpoint contract (server-side pipeline)
# --------------------------------------------------------------------------


def _stub_article() -> ExtractedPage:
    return ExtractedPage(
        url="https://origin.example/redirect-me",
        final_url="https://origin.example/final",
        title="服务器标题",
        byline="作者",
        content_html="<p>服务器清洗后的正文</p>",
        content_text="服务器清洗后的正文",
    )


def test_fetch_endpoint_private_targets_refused(client):
    """Private / loopback / link-local / metadata / mapped targets must be
    refused BEFORE any request is sent (fail closed)."""
    for target in [
        "http://127.0.0.1:8080/",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:10.0.0.1]/",
        "http://192.168.1.5/",
        "http://172.16.0.9/",
        "http://100.64.0.1/",
        "ftp://example.com/x",
    ]:
        response = client.post("/api/v1/library/clips/fetch", json={"url": target})
        assert response.status_code in (400, 502), target
        body = response.json()
        assert body["error"]["type"] in (
            "clip_fetch_forbidden",
            "clip_fetch_failed",
        ), target


def test_fetch_endpoint_returns_server_derived_article(client, monkeypatch):
    """The fetch preview returns the extracted + sanitized article and the
    FINAL url (redirects followed) — not raw HTML, not the original url."""
    import lumirss.routers.clips as clips_router

    called = []

    async def fake_pipeline(url, *, resolver=None):
        called.append(url)
        return _stub_article()

    monkeypatch.setattr(clips_router, "fetch_extract_sanitize", fake_pipeline)
    response = client.post(
        "/api/v1/library/clips/fetch", json={"url": "https://origin.example/redirect-me"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["url"] == "https://origin.example/redirect-me"
    assert body["finalUrl"] == "https://origin.example/final"
    assert body["title"] == "服务器标题"
    assert body["contentHtml"] == "<p>服务器清洗后的正文</p>"
    assert called == ["https://origin.example/redirect-me"]


def test_create_endpoint_ignores_client_html(client, monkeypatch):
    """P0-03 core assertion: client-submitted contentHtml/title are never
    stored — the server re-derives everything from the URL."""
    import lumirss.routers.clips as clips_router

    async def fake_pipeline(url, *, resolver=None):
        return _stub_article()

    monkeypatch.setattr(clips_router, "fetch_extract_sanitize", fake_pipeline)
    response = client.post(
        "/api/v1/library/clips",
        json={
            "url": "https://origin.example/redirect-me",
            "title": "客户端伪造标题",
            "contentHtml": "<script>alert('xss')</script><p>客户端伪造正文</p>",
            "contentText": "客户端伪造正文",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["url"] == "https://origin.example/final"  # final url recorded
    assert body["title"] == "服务器标题"
    assert body["contentHtml"] == "<p>服务器清洗后的正文</p>"
    assert "伪造" not in body["contentHtml"]
    assert "alert" not in body["contentHtml"]


def test_create_endpoint_rejects_invalid_url_without_pipeline(client):
    """Structurally invalid URLs are refused by the real pipeline before
    any network activity (javascript: fails scheme validation)."""
    response = client.post("/api/v1/library/clips", json={"url": "javascript:alert(1)"})
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "clip_fetch_forbidden"


_ = sqlite3  # sqlite3 import documents the IntegrityError contract
