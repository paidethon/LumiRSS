"""F077 关系路径查找 — 环终止、无路径、多路径≤5、深度上限截断、
端点删除→不可达、仅存储边（负向：无边图返回空）。"""

import asyncio

from lumirss.main import app


def run(coroutine):
    return asyncio.run(coroutine)


def _seed(db, item_refs, bindings, relations):
    async def _seed_inner():
        await db.migrate()
        # tags
        for i, name in enumerate(["tagA", "tagB"], start=1):
            await db.execute(
                "INSERT OR IGNORE INTO tags (id, name) VALUES (?, ?)",
                (i, name),
            )
        for i, _ref in enumerate(item_refs, start=1):
            await db.execute(
                "INSERT OR IGNORE INTO library_items (uuid, kind, created_at) VALUES (?, 'bookmark', '2026-09-01T00:00:00Z')",
                (f"u{i}",),
            )
            await db.execute(
                "INSERT OR IGNORE INTO library_bookmarks (item_uuid, item_type, url, rss_item_ref, title, note, created_at) VALUES (?, 'url', ?, NULL, ?, '', '2026-09-01T00:00:00Z')",
                (f"u{i}", f"https://x.example/{i}", f"条目 {i}"),
            )
        # bindings: (item_index, tag_id)
        for item_index, tag_id in bindings:
            await db.execute(
                "INSERT OR IGNORE INTO item_tags (item_ref, tag_id, origin, status, created_at) VALUES (?, ?, 'manual', 'active', '2026-09-01T00:00:00Z')",
                (item_index, tag_id),
            )
        # relations: (src, dst)
        for src, dst in relations:
            await db.execute(
                "INSERT OR IGNORE INTO item_relations (src_ref, dst_ref, note, created_at) VALUES (?, ?, '', '2026-09-01T00:00:00Z')",
                (src, dst),
            )

    return _seed_inner


def _lib(uuid: str) -> str:
    return f"library:{uuid}"


def test_f077_paths_found_cycle_safe_and_cap(client):
    db = app.state.db
    from lumirss.graph_paths import find_paths

    # 图：u1 -tagA- u2 -tagB- u3，另有 u1 -relation- u3（捷径）。
    run(_seed(db, [1, 2, 3], [(1, 1), (2, 1), (2, 2), (3, 2)], [])())
    refs = {1: _lib("u1"), 2: _lib("u2"), 3: _lib("u3")}
    # u1 与 u3 之间再加一条 direct relation，制造环（tag 路径 + 直达）
    async def _extra():
        await db.execute(
            "INSERT OR IGNORE INTO item_relations (src_ref, dst_ref, note, created_at) VALUES (?, ?, '', '2026-09-01T00:00:00Z')",
            (refs[1], refs[3]),
        )

    run(_extra())
    result = run(find_paths(db, src_ref=refs[1], dst_ref=refs[3], max_depth=4))
    assert result["reachable"] is True
    assert 1 <= len(result["paths"]) <= 5
    # 最短路径 = 直达关系（2 节点）
    shortest = result["paths"][0]
    assert shortest["nodes"][0]["ref"] == refs[1]
    assert shortest["nodes"][-1]["ref"] == refs[3]
    assert shortest["edgeKinds"] == ["manual"]
    # 环安全：每条路径节点不重复
    for path in result["paths"]:
        assert len({n["ref"] for n in path["nodes"]}) == len(path["nodes"])

    # src==dst → 平凡路径
    self_result = run(find_paths(db, src_ref=refs[1], dst_ref=refs[1]))
    assert self_result["reachable"] is True
    assert len(self_result["paths"][0]["nodes"]) == 1

    # 深度上限截断：max_depth=1 时 tag 环绕路径不可达，但直达仍可达
    deep = run(find_paths(db, src_ref=refs[2], dst_ref=refs[3], max_depth=1))
    assert deep["reachable"] is False  # u2→u3 需 2 步（u2-tagB-u3）


def test_f077_no_path_endpoint_deleted_and_empty_graph(client):
    db = app.state.db
    from lumirss.graph_paths import find_paths

    # 图：u1 -tagA- u2；u3 孤立（无任何边）
    run(_seed(db, [1, 2, 3], [(1, 1), (2, 1)], [])())
    refs = {1: _lib("u1"), 2: _lib("u2"), 3: _lib("u3")}

    # 端点删除（不在图内）→ 不可达
    result = run(find_paths(db, src_ref=refs[1], dst_ref="library:deleted-uuid"))
    assert result == {"paths": [], "reachable": False}

    # 无边图（孤立节点间）→ 不可达
    no_edge = run(find_paths(db, src_ref=refs[1], dst_ref=refs[3]))
    assert no_edge["reachable"] is False
    assert no_edge["paths"] == []

    # 仅存储边：清空 tags 绑定后，手工关系边仍可寻路（负向验证：无任何边时为空）
    async def _add_relation_then_clear_tags():
        await db.execute(
            "INSERT OR IGNORE INTO item_relations (src_ref, dst_ref, note, created_at) VALUES (?, ?, '', '2026-09-01T00:00:00Z')",
            (refs[1], refs[2]),
        )
        await db.execute("DELETE FROM item_tags")

    run(_add_relation_then_clear_tags())
    manual_only = run(find_paths(db, src_ref=refs[1], dst_ref=refs[2]))
    assert manual_only["reachable"] is True
    assert manual_only["paths"][0]["edgeKinds"] == ["manual"]

    # 路由 404 之外的基本冒烟：graph/path 返回 reachable 结构
    resp = client.post(
        "/api/v1/graph/path",
        json={"srcRef": refs[1], "dstRef": refs[2], "maxDepth": 4},
    )
    assert resp.status_code == 200
    assert resp.json()["reachable"] is True
