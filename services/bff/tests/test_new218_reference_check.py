"""NEW-218 资料引用关系检查 —— 失效引用清单、重关联、保留失效标记。

验收：检查面覆盖 集合条目/手工关联/阅读便签；失效判定 = 解析不可达
（library 指向不存在的行；rss 投影未命中且适配器 EntryNotFound）；
relink 需要新目标真实存在（422 拒绝），目标占用 409；keep-stale 跳过
检查且可解除；A/B 隔离。
"""

import asyncio

from lumirss.entryref import encode_entry_ref
from new21x_isolation import seed_entry

run = asyncio.run

UUID_OK = "11111111-1111-4111-8111-111111111111"
UUID_GONE = "22222222-2222-4222-8222-222222222222"
UUID_NEW = "33333333-3333-4333-8333-333333333333"


class FakeGoneAdapter:
    """模拟 FreshRSS：任何条目都 404（投影未命中 → 确定性 unknown）。"""

    async def get_entry(self, item_id):
        from lumirss.adapters.freshrss import EntryNotFound

        raise EntryNotFound(str(item_id))


def _seed_dangling(client):
    """直接落 3 类引用：1 个有效（bookmark + rss 投影命中）、3 个失效。"""
    app = client.app
    run(app.state.db.migrate())

    async def _seed():
        await app.state.db.execute(
            "INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'bookmark', '2026-09-01T00:00:00+00:00')",
            (UUID_OK,),
        )
        await app.state.db.execute(
            "INSERT INTO library_bookmarks (item_uuid, item_type, url, title, note, created_at) VALUES (?, 'url', 'https://ok.example', '有效', '', '2026-09-01T00:00:00+00:00')",
            (UUID_OK,),
        )
        await app.state.db.execute(
            "INSERT INTO workspace_items (workspace_id, item_ref, position, added_at) VALUES ('read-later', ?, 1, '2026-09-01T00:00:00+00:00')",
            (f"library:{UUID_OK}",),
        )
        await app.state.db.execute(
            "INSERT INTO workspace_items (workspace_id, item_ref, position, added_at) VALUES ('read-later', ?, 2, '2026-09-01T00:00:00+00:00')",
            (f"library:{UUID_GONE}",),
        )
        await app.state.db.execute(
            "INSERT INTO item_relations (src_ref, dst_ref, note, created_at) VALUES (?, ?, '', '2026-09-01T00:00:00+00:00')",
            (f"library:{UUID_OK}", f"library:{UUID_GONE}"),
        )
        await app.state.db.execute(
            "INSERT INTO reading_notes (entry_ref, note, updated_at) VALUES (?, '便签', '2026-09-01T00:00:00+00:00')",
            (f"rss:{encode_entry_ref('gone-entry')}",),
        )

    run(_seed())


def test_new218_check_relink_and_keep_stale(client):
    seed_entry(client, "live-entry", title="活着的文章")
    _seed_dangling(client)
    client.app.state.freshrss_adapter = FakeGoneAdapter()
    try:
        report = client.post("/api/v1/references/check", json={})
        assert report.status_code == 200, report.text
        body = report.json()
        issues = {(i["surface"], i["ref"]) for i in body["issues"]}
        assert ("workspaces", f"library:{UUID_GONE}") in issues
        assert ("relations", f"library:{UUID_GONE}") in issues
        assert ("notes", f"rss:{encode_entry_ref('gone-entry')}") in issues
        assert body["keptStale"] == []
        assert body["checked"] == 3  # 去重后的待检引用（OK/GONE/失效便签）
    finally:
        client.app.state.freshrss_adapter = None

    # relink：新目标必须真实存在（未播种的 UUID → 422）
    relink_missing = client.post(
        "/api/v1/references/relink",
        json={
            "surface": "workspaces",
            "locator": "read-later",
            "oldRef": f"library:{UUID_GONE}",
            "newRef": f"library:{UUID_NEW}",
        },
    )
    assert relink_missing.status_code == 422
    assert relink_missing.json()["error"]["type"] == "invalid_reference_check"

    seed_entry(client, "replacement", title="替代文章")
    relinked = client.post(
        "/api/v1/references/relink",
        json={
            "surface": "workspaces",
            "locator": "read-later",
            "oldRef": f"library:{UUID_GONE}",
            "newRef": "rss:" + encode_entry_ref("replacement"),
        },
    )
    assert relinked.status_code == 200, relinked.text
    members = {
        r["item_ref"]
        for r in run(
            client.app.state.db.fetch_all(
                "SELECT item_ref FROM workspace_items WHERE workspace_id = 'read-later'"
            )
        )
    }
    assert f"library:{UUID_GONE}" not in members
    assert "rss:" + encode_entry_ref("replacement") in members

    # 集合唯一约束：relink 到已存在的成员 → 409
    conflict = client.post(
        "/api/v1/references/relink",
        json={
            "surface": "workspaces",
            "locator": "read-later",
            "oldRef": f"library:{UUID_OK}",
            "newRef": "rss:" + encode_entry_ref("replacement"),
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["type"] == "reference_check_conflict"

    # 保留失效标记：便签的失效引用登记后不再报警（进入 keptStale），可解除
    keep = client.post(
        "/api/v1/references/keep-stale",
        json={
            "surface": "notes",
            "locator": "reading_note",
            "ref": "rss:" + encode_entry_ref("gone-entry"),
        },
    )
    assert keep.status_code == 200, keep.text
    client.app.state.freshrss_adapter = FakeGoneAdapter()
    try:
        report = client.post("/api/v1/references/check", json={"surfaces": ["notes"]}).json()
        assert report["issues"] == []
        assert len(report["keptStale"]) == 1
    finally:
        client.app.state.freshrss_adapter = None
    keeps = run(
        client.app.state.db.fetch_all("SELECT id FROM new218_stale_keeps")
    )
    assert (
        client.delete(f"/api/v1/references/keep-stale/{keeps[0]['id']}").status_code
        == 204
    )
    assert (
        client.delete(f"/api/v1/references/keep-stale/{keeps[0]['id']}").status_code
        == 404
    )


def test_new218_per_user_isolation(monkeypatch, tmp_path):
    """per-user 库：A 检查不到也修不到 B 的引用候选。"""
    from new21x_isolation import build_two_user_client, isolated_auth_env

    isolated_auth_env(monkeypatch, tmp_path)
    for client, owner, member in build_two_user_client():
        created = client.post(
            "/api/v1/library/bookmarks",
            json={"url": "https://b.example/x", "title": "乙的有效书签"},
            headers=member,
        )
        assert created.status_code == 201
        ref = created.json()["ref"]
        ws = client.post(
            "/api/v1/workspaces", json={"name": "乙的集合"}, headers=member
        ).json()["id"]
        client.post(
            f"/api/v1/workspaces/{ws}/items", json={"itemRef": ref}, headers=member
        )

        client.app.state.freshrss_adapter = FakeGoneAdapter()
        try:
            # A 检查：没有 B 的任何候选（A 自己无候选 → checked 0）
            owner_report = client.post(
                "/api/v1/references/check", json={}, headers=owner
            ).json()
            all_refs = {i["ref"] for i in owner_report["issues"]} | {
                k["ref"] for k in owner_report["keptStale"]
            }
            assert ref not in all_refs
            assert owner_report["checked"] == 0
            # B 自己能查到（有效书签不失效）
            member_report = client.post(
                "/api/v1/references/check", json={}, headers=member
            ).json()
            assert member_report["checked"] == 1
            assert member_report["issues"] == []
        finally:
            client.app.state.freshrss_adapter = None
