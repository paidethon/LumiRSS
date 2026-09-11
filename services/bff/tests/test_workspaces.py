"""Workspace API tests (phase2 M1).

Reserved read-later protection, mixed rss:/library: membership, ordering,
idempotent add/remove, stale-ref behaviour when FreshRSS loses an entry,
and the unified resolve endpoint.
"""

from typing import Any

import pytest

from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.models import EntryDetail


class _FakeAdapter:
    """Minimal FreshRSSAdapter stand-in for resolve-path tests."""

    def __init__(self, entries: dict[str, EntryDetail]) -> None:
        self._entries = entries

    async def get_entry(self, item_id: str) -> EntryDetail:
        entry = self._entries.get(item_id)
        if entry is None:
            from lumirss.adapters.freshrss import EntryNotFound

            raise EntryNotFound(item_id)
        return entry


def _entry_detail(item_id: str, title: str) -> EntryDetail:
    return EntryDetail(
        entryRef=encode_entry_ref(item_id),
        title=title,
        feedTitle="测试源",
        url=f"https://example.com/{item_id}",
        publishedAt="2026-09-01T00:00:00+00:00",
        read=False,
        starred=False,
        contentText=f"{title} 的正文文本。",
        contentHtml=None,
    )


@pytest.fixture()
def fake_rss_entries():
    """Install a fake adapter; returns the mutable entry table."""
    entries: dict[str, EntryDetail] = {
        "1001": _entry_detail("1001", "vLLM V1"),
        "1002": _entry_detail("1002", "本地翻译笔记"),
    }
    app.state.freshrss_adapter = _FakeAdapter(entries)
    yield entries
    app.state.freshrss_adapter = None


def _rss_ref(item_id: str) -> str:
    return "rss:" + encode_entry_ref(item_id)


def test_read_later_seeded_reserved_and_undeletable(client):
    listing = client.get("/api/v1/workspaces").json()["items"]
    read_later = [w for w in listing if w["id"] == "read-later"]
    assert len(read_later) == 1
    assert read_later[0]["reserved"] is True

    assert client.delete("/api/v1/workspaces/read-later").status_code == 409
    assert (
        client.patch(
            "/api/v1/workspaces/read-later", json={"name": "改名"}
        ).status_code
        == 409
    )
    conflict = client.post("/api/v1/workspaces", json={"name": "read-later"})
    # Creating a workspace *named* read-later is allowed but id differs.
    assert conflict.status_code == 201
    assert conflict.json()["id"] != "read-later"


def test_workspace_crud_and_reserved_shape(client):
    created = client.post("/api/v1/workspaces", json={"name": "AI 研究"})
    assert created.status_code == 201
    workspace_id = created.json()["id"]

    renamed = client.patch(
        f"/api/v1/workspaces/{workspace_id}", json={"name": "考研"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "考研"

    assert client.delete(f"/api/v1/workspaces/{workspace_id}").status_code == 204
    assert client.get(f"/api/v1/workspaces/{workspace_id}").status_code == 404

    empty_name = client.post("/api/v1/workspaces", json={"name": "   "})
    assert empty_name.status_code == 400


def test_mixed_refs_add_order_remove(client, fake_rss_entries):
    bookmark = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.com/lib", "title": "库条目"},
    ).json()["ref"]

    added_rss = client.post(
        "/api/v1/workspaces/read-later/items", json={"itemRef": _rss_ref("1001")}
    )
    assert added_rss.status_code == 201
    added_lib = client.post(
        "/api/v1/workspaces/read-later/items", json={"itemRef": bookmark}
    )
    assert added_lib.status_code == 201

    # Idempotent add: same ref returns the existing slot, count stays 2.
    repeat = client.post(
        "/api/v1/workspaces/read-later/items", json={"itemRef": bookmark}
    )
    assert repeat.status_code == 201
    assert repeat.json()["position"] == added_lib.json()["position"]
    items = client.get("/api/v1/workspaces/read-later/items").json()["items"]
    assert len(items) == 2

    # Reorder puts the library item first.
    reordered = client.patch(
        "/api/v1/workspaces/read-later/items",
        json={"itemRefs": [bookmark, _rss_ref("1001")]},
    )
    positions = {i["itemRef"]: i["position"] for i in reordered.json()["items"]}
    assert positions[bookmark] < positions[_rss_ref("1001")]

    # Unknown ref in reorder is refused, not silently ignored.
    bad = client.patch(
        "/api/v1/workspaces/read-later/items",
        json={"itemRefs": [bookmark, _rss_ref("9999")]},
    )
    assert bad.status_code == 400

    # Remove works and reports honestly.
    assert (
        client.delete(
            f"/api/v1/workspaces/read-later/items/{bookmark}"
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/api/v1/workspaces/read-later/items/{bookmark}"
        ).status_code
        == 400
    )


def test_invalid_refs_are_refused(client):
    for bad_ref in ["library:nope", "e1.notvad", "workspace:thing", "rss:garbage"]:
        response = client.post(
            "/api/v1/workspaces/read-later/items", json={"itemRef": bad_ref}
        )
        assert response.status_code in (400, 404), bad_ref


def test_contents_resolve_both_domains_and_mark_stale(client, fake_rss_entries):
    bookmark = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.com/lib2", "title": "库条目二"},
    ).json()["ref"]
    client.post(
        "/api/v1/workspaces/read-later/items", json={"itemRef": _rss_ref("1001")}
    )
    client.post("/api/v1/workspaces/read-later/items", json={"itemRef": bookmark})

    contents = client.get("/api/v1/workspaces/read-later/contents")
    assert contents.status_code == 200
    views: list[dict[str, Any]] = contents.json()["items"]
    assert all(not view["stale"] for view in views)
    rss_view = next(v for v in views if v["domain"] == "rss")
    assert rss_view["title"] == "vLLM V1"
    assert rss_view["source"] == "测试源"
    lib_view = next(v for v in views if v["domain"] == "library")
    assert lib_view["kind"] == "bookmark"

    # The entry disappears upstream → stale view, row NOT auto-deleted.
    del fake_rss_entries["1001"]
    after = client.get("/api/v1/workspaces/read-later/contents").json()["items"]
    stale = next(v for v in after if v["ref"] == _rss_ref("1001"))
    assert stale["stale"] is True
    items = client.get("/api/v1/workspaces/read-later/items").json()["items"]
    assert len(items) == 2


def test_resolve_endpoint_batch_and_limit(client):
    response = client.post("/api/v1/resolve", json={"refs": []})
    assert response.status_code == 400
    response = client.post("/api/v1/resolve", json={"refs": ["bad"] * 2})
    assert response.status_code == 400

    bookmark = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.com/r", "title": "解析我"},
    ).json()["ref"]
    resolved = client.post("/api/v1/resolve", json={"refs": [bookmark]})
    assert resolved.status_code == 200
    view = resolved.json()["items"][0]
    assert view["stale"] is False
    assert view["title"] == "解析我"
