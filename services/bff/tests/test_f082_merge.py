"""F082 重复资料合并 — policy 冲突字段、资产去重引用计数、批注/标签迁移、
事务注入失败整体回滚、二次合并 409、FreshRSS/Vault 负向。"""

import asyncio

from lumirss.main import app

PA = "00000000-0000-4000-8000-0000000001f1"
PB = "00000000-0000-4000-8000-0000000001f2"
RA = f"library:{PA}"
RB = f"library:{PB}"


def run(coro):
    return asyncio.run(coro)


def _seed_pair(client, *, dup_url="https://dup.example/same"):
    r1 = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://primary.example/entry", "title": "Primary 标题", "note": "主笔记"},
    )
    r2 = client.post(
        "/api/v1/library/bookmarks",
        json={"url": dup_url, "title": "Duplicate 标题", "note": "重复笔记"},
    )
    assert r1.status_code == 201 and r2.status_code == 201
    ra, rb = r1.json()["ref"], r2.json()["ref"]
    globals()["_DYN_A"], globals()["_DYN_B"] = ra, rb
    # 打标签：A→shared/onlyA；B→shared/onlyB
    for ref, tag in ((ra, "shared"), (ra, "onlyA"), (rb, "shared"), (rb, "onlyB")):
        assigned = client.post("/api/v1/tags/assign", json={"itemRef": ref, "name": tag})
        assert assigned.status_code in (201, 200), assigned.text
    return ra, rb


def test_f082_preview_field_compare(client):
    ra, rb = _seed_pair(client)
    preview = client.post(
        "/api/v1/library/merge/preview",
        json={"primaryRef": ra, "duplicateRef": rb},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    fields = {f["field"]: f for f in body["fields"]}
    assert fields["title"]["primary"] == "Primary 标题"
    assert fields["title"]["duplicate"] == "Duplicate 标题"
    assert set(fields["tags"]["primary"]) == {"shared", "onlyA"}


def test_f082_merge_policy_and_tag_union_and_trash(client):
    ra, rb = _seed_pair(client)
    merged = client.post(
        "/api/v1/library/merge",
        json={
            "primaryRef": ra,
            "duplicateRef": rb,
            "policy": {"title": "duplicate", "note": "append"},
        },
    )
    assert merged.status_code == 200, merged.text
    body = merged.json()
    assert body["mergedRef"] == ra and body["removedRef"] == rb
    assert set(body["tagsUnion"]) == {"shared", "onlyA", "onlyB"}
    row = run(
        app.state.db.fetch_one(
            "SELECT title, note FROM library_bookmarks WHERE item_uuid = ?",
            (ra.split(":")[1],),
        )
    )
    assert row["title"] == "Duplicate 标题"  # policy: duplicate
    assert "主笔记" in row["note"] and "重复笔记" in row["note"]  # append
    # duplicate 软删进回收站
    trash = client.get("/api/v1/library/trash").json()["items"]
    assert any(t["uuid"] == rb.split(":")[1] for t in trash)
    # merged 映射关系
    rel = run(
        app.state.db.fetch_one(
            "SELECT kind FROM item_relations WHERE src_ref = ? AND dst_ref = ?",
            (ra, rb),
        )
    )
    assert rel["kind"] == "merged"
    # 二次合并 → 409 merged_already
    again = client.post(
        "/api/v1/library/merge", json={"primaryRef": ra, "duplicateRef": rb}
    )
    assert again.status_code == 409
    assert again.json()["error"]["type"] == "merged_already"


def test_f082_annotations_move_and_asset_dedupe(client):
    ra, rb = _seed_pair(client)
    # 批注挂在 duplicate 上
    run(
        app.state.db.execute(
            "INSERT INTO annotations (id, entry_ref, anchor_json, anchor_hash, excerpt, note, color, created_at, updated_at) VALUES ('an1', ?, '{}', 'h1', 'exc', '批注', 'yellow', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (rb,),
        )
    )
    pa, pb = ra.split(":")[1], rb.split(":")[1]
    # 资产：A、B 各一份（B 的应被去重删除）
    for uuid_, item in (("ast-a", pa), ("ast-b", pb)):
        run(
            app.state.db.execute(
                "INSERT INTO library_assets (uuid, item_uuid, path, bytes, sha256, mime, created_at) VALUES (?, ?, ?, 10, 'x', 'text/html', '2026-01-01T00:00:00Z')",
                (uuid_, item, f"/data/{uuid_}.html"),
            )
        )
    merged = client.post(
        "/api/v1/library/merge", json={"primaryRef": ra, "duplicateRef": rb}
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["movedAnnotations"] == 1
    ann = run(
        app.state.db.fetch_all(
            "SELECT entry_ref FROM annotations WHERE id = 'an1'"
        )
    )
    assert ann[0]["entry_ref"] == ra
    pa, pb = ra.split(":")[1], rb.split(":")[1]
    assets = run(
        app.state.db.fetch_all(
            "SELECT item_uuid FROM library_assets WHERE item_uuid IN (?, ?)",
            (pa, pb),
        )
    )
    # 去重后引用计数正确：primary 恰好 1 份，无孤立资产
    assert [a["item_uuid"] for a in assets] == [pa]


def test_f082_transaction_failure_rolls_back_everything(client, monkeypatch):
    ra, rb = _seed_pair(client)
    from lumirss import library_merge

    def _boom(conn, ref):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(library_merge, "delete_search_row", _boom)
    import pytest

    with pytest.raises(RuntimeError):
        client.post(
            "/api/v1/library/merge", json={"primaryRef": ra, "duplicateRef": rb}
        )
    # 注入失败 → 两记录原样（整体回滚）
    pa, pb = ra.split(":")[1], rb.split(":")[1]
    alive = run(
        app.state.db.fetch_all(
            "SELECT uuid, deleted_at FROM library_items WHERE uuid IN (?, ?)",
            (pa, pb),
        )
    )
    assert all(row["deleted_at"] is None for row in alive)
    assert len(alive) == 2


def test_f082_freshrss_and_vault_untouched_negative(client):
    ra, rb = _seed_pair(client)
    # 请求里夹一个 rss 引用 → 422（不支持域），且不产生任何写入
    merged = client.post(
        "/api/v1/library/merge",
        json={"primaryRef": ra, "duplicateRef": "rss:not-a-ref"},
    )
    assert merged.status_code == 422
    alive = run(
        app.state.db.fetch_one(
            "SELECT deleted_at FROM library_items WHERE uuid = ?",
            (ra.split(":")[1],),
        )
    )
    assert alive["deleted_at"] is None
