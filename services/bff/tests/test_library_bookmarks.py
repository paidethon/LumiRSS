"""Library bookmark API tests (phase2 M1).

Covers CRUD, scheme whitelist, duplicate idempotency, rss-ref bookmarks
(no body copy is even possible — only the ref + metadata are stored),
list pagination and the stable error envelope.
"""


from lumirss.entryref import encode_entry_ref
from lumirss.main import app


def test_url_bookmark_create_and_duplicate_idempotent(client):
    first = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.com/article", "title": "文章"},
    )
    assert first.status_code == 201
    body = first.json()
    assert body["ref"].startswith("library:")
    assert body["itemType"] == "url"

    duplicate = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.com/article", "title": "重复标题"},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["ref"] == body["ref"]
    # The canonical row keeps the first title.
    assert duplicate.json()["title"] == "文章"


def test_rejects_non_http_schemes(client):
    for url in ["javascript:alert(1)", "ftp://x.com/f", "file:///etc/passwd", "notaurl"]:
        response = client.post(
            "/api/v1/library/bookmarks", json={"url": url, "title": "x"}
        )
        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_bookmark"


def test_rejects_exactly_one_of_url_or_rss_ref(client):
    both = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://a.com", "rssItemRef": "rss:bogus", "title": "x"},
    )
    assert both.status_code == 400
    neither = client.post("/api/v1/library/bookmarks", json={"title": "x"})
    assert neither.status_code == 400


def test_rss_ref_bookmark_stores_ref_only(client):
    entry_ref = encode_entry_ref("1001")
    response = client.post(
        "/api/v1/library/bookmarks",
        json={"rssItemRef": f"rss:{entry_ref}", "title": "RSS 文章"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["itemType"] == "rss"
    assert body["rssItemRef"] == f"rss:{entry_ref}"
    assert body["url"] is None

    # Duplicate rss ref converges on the same library item.
    again = client.post(
        "/api/v1/library/bookmarks",
        json={"rssItemRef": f"rss:{entry_ref}", "title": "RSS 文章"},
    )
    assert again.json()["ref"] == body["ref"]

    # A malformed rss ref is refused (never stored as opaque junk).
    bad = client.post(
        "/api/v1/library/bookmarks",
        json={"rssItemRef": "rss:garbage", "title": "x"},
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["type"] == "invalid_bookmark"


def test_update_and_delete_bookmark(client):
    created = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.com/note", "title": "原题", "note": "n"},
    )
    ref = created.json()["ref"]
    uuid = ref.split(":", 1)[1]

    patched = client.patch(
        f"/api/v1/library/bookmarks/{uuid}", json={"note": "更新后"}
    )
    assert patched.status_code == 200
    assert patched.json()["note"] == "更新后"
    assert patched.json()["title"] == "原题"

    assert client.delete(f"/api/v1/library/bookmarks/{uuid}").status_code == 204
    # Identity row is gone too — the ref no longer resolves.
    assert client.delete(f"/api/v1/library/bookmarks/{uuid}").status_code == 404
    resolve = client.post("/api/v1/resolve", json={"refs": [ref]})
    assert resolve.json()["items"][0]["stale"] is True


def test_list_pagination_and_search(client):
    for index in range(5):
        client.post(
            "/api/v1/library/bookmarks",
            json={"url": f"https://example.com/{index}", "title": f"文章{index}"},
        )
    page = client.get("/api/v1/library/bookmarks", params={"limit": 3})
    body = page.json()
    assert len(body["items"]) == 3
    assert body["nextCursor"] is not None

    following = client.get(
        "/api/v1/library/bookmarks",
        params={"limit": 3, "cursor": body["nextCursor"]},
    )
    assert len(following.json()["items"]) == 2

    hits = client.get("/api/v1/library/bookmarks", params={"q": "文章3"})
    assert len(hits.json()["items"]) == 1
    assert hits.json()["items"][0]["title"] == "文章3"


def test_rss_body_is_never_copied_into_lumi(client):
    """Ownership invariant: only library rows exist; no content column."""
    entry_ref = encode_entry_ref("42")
    client.post(
        "/api/v1/library/bookmarks",
        json={"rssItemRef": f"rss:{entry_ref}", "title": "仅引用"},
    )
    with app.state.db._connect() as conn:  # noqa: SLF001 — test-level probe
        columns = [
            row[1]
            for row in conn.execute("PRAGMA table_info(library_bookmarks)").fetchall()
        ]
    assert "content" not in columns
    assert "content_html" not in columns
    assert "content_text" not in columns
