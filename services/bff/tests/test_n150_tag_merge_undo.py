"""N150 标签合并撤销 — 快照、恢复、双击 409、TTL 404。

- 合并前在同一事务内快照源绑定；撤销重建源标签（新 id）并原样恢复
  全部绑定（含被折叠的重复绑定）；目标保留合并来的绑定；
- 撤销后快照保留：再次撤销 → 409（源标签名已被占用，绝不二次恢复）；
- 无快照 → 404；超过 24h 窗口 → 404（快照清除）；
- 新合并覆盖旧快照（只可撤销最近一次）。
"""

import asyncio

import pytest

from lumirss.storage import Database
from lumirss.tags import (
    TagMergeSourceRecreated,
    TagMergeUndoNotFound,
    TagStore,
)


def _run(coroutine):

    return asyncio.run(coroutine)


@pytest.fixture()
def env(tmp_path):
    from lumirss.library import LibraryStore

    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    return {"db": db, "tags": TagStore(db), "library": LibraryStore(db)}


async def _bookmark(library, url: str) -> str:
    created, _flag = await library.create_url_bookmark(
        url=url, title=f"t-{url[-6:]}"
    )
    return created.ref


def _tag_id(tags, name: str) -> int:
    return next(t.id for t in _run(tags.list_tags()) if t.name == name)


def test_merge_snapshots_and_undo_restores_bindings(env):
    tags, library = env["tags"], env["library"]
    ref_a = _run(_bookmark(library, "https://example.com/a"))
    ref_b = _run(_bookmark(library, "https://example.com/b"))
    _run(tags.attach(ref_a, "源标签"))
    _run(tags.attach(ref_b, "源标签"))
    _run(tags.attach(ref_b, "目标标签"))
    source_id = _tag_id(tags, "源标签")
    target_id = _tag_id(tags, "目标标签")

    merge = _run(tags.merge(source_id, target_id))
    assert merge["movedBindings"] == 1
    assert merge["dedupedBindings"] == 1

    undo = _run(tags.undo_merge())
    assert undo["name"] == "源标签"
    assert undo["targetTagId"] == target_id
    assert undo["restoredBindings"] == 2  # a、b 的源绑定都回来了
    assert undo["sourceTagId"] != source_id  # 重建 = 新 id

    names = {t.name for t in _run(tags.list_tags())}
    assert "源标签" in names and "目标标签" in names
    for ref in (ref_a, ref_b):
        bound = {t["name"] for t in _run(tags.tags_for_item(ref))}
        assert "源标签" in bound  # 撤销恢复
        assert "目标标签" in bound  # 目标保留合并来的绑定


def test_double_undo_conflicts_409(env):
    tags, library = env["tags"], env["library"]
    ref = _run(_bookmark(library, "https://example.com/x"))
    _run(tags.attach(ref, "临时标签"))
    # 建一个真实目标标签。
    ref2 = _run(_bookmark(library, "https://example.com/y"))
    _run(tags.attach(ref2, "目标标签"))
    _run(tags.merge(_tag_id(tags, "临时标签"), _tag_id(tags, "目标标签")))

    _run(tags.undo_merge())  # 第一次撤销成功
    with pytest.raises(TagMergeSourceRecreated):
        _run(tags.undo_merge())  # 第二次：源已重建 → 409，绝不二次恢复


def test_undo_without_snapshot_404(env):
    with pytest.raises(TagMergeUndoNotFound):
        _run(env["tags"].undo_merge())


def test_undo_ttl_expired_404_and_snapshot_cleared(env):
    tags, db, library = env["tags"], env["db"], env["library"]
    ref = _run(_bookmark(library, "https://example.com/ttl"))
    _run(tags.attach(ref, "过期标签"))
    ref2 = _run(_bookmark(library, "https://example.com/ttl2"))
    _run(tags.attach(ref2, "存活标签"))
    _run(tags.merge(_tag_id(tags, "过期标签"), _tag_id(tags, "存活标签")))

    async def _expire():
        await db.execute(
            "UPDATE tag_merge_undo SET created_at = '2020-01-01T00:00:00+00:00' WHERE id = 1",
            (),
        )

    _run(_expire())
    with pytest.raises(TagMergeUndoNotFound):
        _run(tags.undo_merge())  # TTL 24h 已过 → 404
    row = _run(db.fetch_one("SELECT id FROM tag_merge_undo WHERE id = 1", ()))
    assert row is None  # 过期快照已清除


def test_new_merge_replaces_previous_snapshot(env):
    tags, library = env["tags"], env["library"]
    ref_a = _run(_bookmark(library, "https://example.com/m1"))
    ref_b = _run(_bookmark(library, "https://example.com/m2"))
    ref_c = _run(_bookmark(library, "https://example.com/m3"))
    _run(tags.attach(ref_a, "标签一"))
    _run(tags.attach(ref_b, "标签二"))
    _run(tags.attach(ref_c, "标签三"))
    _run(tags.merge(_tag_id(tags, "标签一"), _tag_id(tags, "标签二")))
    _run(tags.merge(_tag_id(tags, "标签二"), _tag_id(tags, "标签三")))

    undo = _run(tags.undo_merge())  # 只能撤销最近一次（标签二 → 标签三）
    assert undo["name"] == "标签二"
    assert undo["restoredBindings"] == 2  # a、b 的绑定（合并自标签一 + 原有）

    names = {t.name for t in _run(tags.list_tags())}
    assert "标签二" in names
    assert "标签一" not in names  # 第一次合并已不可撤销
    bound = {t["name"] for t in _run(tags.tags_for_item(ref_a))}
    assert bound == {"标签二", "标签三"}


# ---- 路由端到端 -------------------------------------------------------------

def test_merge_undo_routes_end_to_end(client):
    created = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.com/u1", "title": "u1"},
    ).json()
    client.post("/api/v1/tags/assign", json={"itemRef": created["ref"], "name": "旧名"})
    client.post("/api/v1/tags/assign", json={"itemRef": created["ref"], "name": "新名"})
    tags = {t["name"]: t["id"] for t in client.get("/api/v1/tags").json()["items"]}

    merged = client.post(
        "/api/v1/tags/merge", json={"sourceId": tags["旧名"], "targetId": tags["新名"]}
    )
    assert merged.status_code == 200

    undone = client.post("/api/v1/tags/merge/undo")
    assert undone.status_code == 200
    body = undone.json()
    assert body["name"] == "旧名"
    assert body["restoredBindings"] == 1
    remaining = {t["name"] for t in client.get("/api/v1/tags").json()["items"]}
    assert "旧名" in remaining

    double = client.post("/api/v1/tags/merge/undo")
    assert double.status_code == 409
    assert double.json()["error"]["type"] == "tag_merge_source_recreated"


def test_undo_route_404_without_snapshot(client):
    missing = client.post("/api/v1/tags/merge/undo")
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "tag_merge_undo_not_found"
