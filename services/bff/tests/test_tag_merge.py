"""标签合并（pool #16）：预览计数、事务化执行、重复绑定去重、404/400
语义。目标条目与其它标签关系不受影响；FreshRSS 分类不在 Lumi 域。"""

import pytest

from lumirss.library import LibraryStore
from lumirss.storage import Database
from lumirss.tags import TagInvalid, TagNotFound, TagStore


def _run(coroutine):
    import asyncio

    return asyncio.run(coroutine)


@pytest.fixture()
def env(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    return {"db": db, "tags": TagStore(db), "library": LibraryStore(db)}


async def _bookmark(library: LibraryStore, url: str) -> str:
    created, _created_flag = await library.create_url_bookmark(
        url=url, title=f"t-{url[-6:]}"
    )
    return created.ref


async def _bind_all(tags: TagStore, ref: str, name: str) -> None:
    await tags.attach(ref, name)


def test_merge_preview_counts_move_and_overlap(env):
    tags, library = env["tags"], env["library"]
    ref_a = _run(_bookmark(library, "https://example.com/a"))
    ref_b = _run(_bookmark(library, "https://example.com/b"))
    ref_c = _run(_bookmark(library, "https://example.com/c"))
    _run(tags.attach(ref_a, "源标签"))
    _run(tags.attach(ref_b, "源标签"))
    _run(tags.attach(ref_b, "目标标签"))  # b 同时有两个标签 → 源去重
    _run(tags.attach(ref_c, "目标标签"))
    source = next(t for t in _run(tags.list_tags()) if t.name == "源标签")
    target = next(t for t in _run(tags.list_tags()) if t.name == "目标标签")

    preview = _run(tags.merge_preview(source.id, target.id))
    assert preview["bindings"] == 2
    assert preview["overlaps"] == 1  # b 已有目标标签
    assert preview["willMove"] == 1  # a 会移过去


def test_merge_is_atomic_moves_dedupes_and_deletes_source(env):
    tags, library = env["tags"], env["library"]
    ref_a = _run(_bookmark(library, "https://example.com/a"))
    ref_b = _run(_bookmark(library, "https://example.com/b"))
    _run(tags.attach(ref_a, "源标签"))
    _run(tags.attach(ref_b, "源标签"))
    _run(tags.attach(ref_b, "目标标签"))
    source = next(t for t in _run(tags.list_tags()) if t.name == "源标签")
    target = next(t for t in _run(tags.list_tags()) if t.name == "目标标签")

    result = _run(tags.merge(source.id, target.id))
    assert result["targetTagId"] == target.id
    assert result["movedBindings"] == 1  # a 移动
    assert result["dedupedBindings"] == 1  # b 的源绑定折叠

    names = sorted(t.name for t in _run(tags.list_tags()))
    assert "源标签" not in names
    # 目标绑定完好：a、b 都挂着目标标签。
    for ref in (ref_a, ref_b):
        bound = [t["name"] for t in _run(tags.tags_for_item(ref))]
        assert "目标标签" in bound

    with pytest.raises(TagNotFound):
        _run(tags.merge(source.id, target.id))  # 源已不存在


def test_merge_rejects_same_tag_and_missing_ids(env):
    tags, library = env["tags"], env["library"]
    ref_a = _run(_bookmark(library, "https://example.com/a"))
    _run(tags.attach(ref_a, "唯一标签"))
    tag = next(t for t in _run(tags.list_tags()) if t.name == "唯一标签")
    with pytest.raises(TagInvalid):
        _run(tags.merge(tag.id, tag.id))
    with pytest.raises(TagNotFound):
        _run(tags.merge(999999, tag.id))
    with pytest.raises(TagNotFound):
        _run(tags.merge_preview(999999, tag.id))


def test_merge_routes_end_to_end(client):
    created = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.com/m1", "title": "m1"},
    ).json()
    client.post("/api/v1/tags/assign", json={"itemRef": created["ref"], "name": "旧名"})
    client.post("/api/v1/tags/assign", json={"itemRef": created["ref"], "name": "新名"})
    tags = {t["name"]: t["id"] for t in client.get("/api/v1/tags").json()["items"]}

    preview = client.get(
        "/api/v1/tags/merge/preview",
        params={"sourceId": tags["旧名"], "targetId": tags["新名"]},
    )
    assert preview.status_code == 200
    assert preview.json()["bindings"] == 1

    merged = client.post(
        "/api/v1/tags/merge", json={"sourceId": tags["旧名"], "targetId": tags["新名"]}
    )
    assert merged.status_code == 200
    remaining = {t["name"] for t in client.get("/api/v1/tags").json()["items"]}
    assert "旧名" not in remaining
