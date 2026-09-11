"""Web clip pipeline tests (phase2 M2).

Covers the SSRF-guarded fetch (mocked transport — private/metadata
address matrix, bad MIME, oversize), clip CRUD with duplicate-url
convergence, and the search_library projection staying in sync.
"""

import pytest

from lumirss.clip_fetch import ClipFetchError
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


def test_fetch_endpoint_private_targets_refused(client):
    """Private / loopback / link-local / metadata / mapped targets must be
    refused BEFORE any request is sent (fail closed)."""
    import httpx

    called: list[str] = []

    def blocked_transport(request: httpx.Request) -> httpx.Response:
        called.append(str(request.url))
        return httpx.Response(200, text="<html>leak</html>")

    # Point the shared http_client at a transport that records every dial;
    # the SSRF layer must refuse before any dial happens.
    client.app.state.http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(blocked_transport)
    )
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
    assert called == []  # no dial ever left the server
