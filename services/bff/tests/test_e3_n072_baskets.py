"""N072 批注精选篮 — CRUD / 导出过滤 / broken 标注 / 跨用户隔离。

- 篮 CRUD：创建、重命名、删除（成员关系级联，批注本体不动）、计数；
- 成员：幂等加入（重复加入 skipped）、未知批注 honest skipped、移除；
- 导出：POST /annotations/export basketId= 只含篮成员（复用既有导出
  路径与格式）；basketId 与 entryRefs/q 互斥 → 422；
- broken：批注被删除后成员行保留且 broken=true（annotation=null）；
  锚点 stale 同样 surfaced 为 broken；
- 隔离：per-user 库——他人批注 id 加入 → annotation_not_found。
"""

import asyncio

from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.user_scope import user_context


def _run(coroutine):
    return asyncio.run(coroutine)


def _annotation(client, entry_ref: str, excerpt: str, marker: int) -> dict:
    response = client.post(
        "/api/v1/annotations",
        json={
            "entryRef": entry_ref,
            "anchor": {"paraId": f"p-{marker}", "prefix": "", "exact": excerpt, "suffix": ""},
            "excerpt": excerpt,
            "note": f"批注 {marker}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_n072_basket_crud_and_membership(client):
    """创建/重命名/删除 + 幂等加入 + 未知批注跳过 + 计数诚实。"""
    ref = encode_entry_ref("9201")
    a1 = _annotation(client, ref, "第一条精选摘录", 0)
    a2 = _annotation(client, ref, "第二条精选摘录", 1)

    # 创建
    created = client.post("/api/v1/annotation-baskets", json={"name": "研究精选"})
    assert created.status_code == 201, created.text
    basket = created.json()
    assert basket["name"] == "研究精选"
    empty_name = client.post("/api/v1/annotation-baskets", json={"name": "  "})
    assert empty_name.status_code == 422

    # 加入（含未知 id → skipped，不中断）
    added = client.post(
        f"/api/v1/annotation-baskets/{basket['id']}/items",
        json={"annotationIds": [a1["id"], a2["id"], "nonexistent"]},
    )
    assert added.status_code == 200, added.text
    body = added.json()
    assert body["added"] == [a1["id"], a2["id"]]
    assert body["skipped"] == [
        {"annotationId": "nonexistent", "reason": "annotation_not_found"}
    ]

    # 幂等：重复加入 → already_member
    again = client.post(
        f"/api/v1/annotation-baskets/{basket['id']}/items",
        json={"annotationIds": [a1["id"]]},
    )
    assert again.status_code == 200
    assert again.json()["added"] == []
    assert again.json()["skipped"] == [
        {"annotationId": a1["id"], "reason": "already_member"}
    ]

    listing = client.get("/api/v1/annotation-baskets")
    assert listing.status_code == 200
    baskets = listing.json()["items"]
    assert len(baskets) == 1
    assert baskets[0]["itemCount"] == 2

    # 成员明细（加入顺序；broken=false）
    items = client.get(f"/api/v1/annotation-baskets/{basket['id']}/items")
    assert items.status_code == 200
    entries = items.json()["items"]
    assert [e["annotationId"] for e in entries] == [a1["id"], a2["id"]]
    assert all(e["broken"] is False for e in entries)
    assert entries[0]["annotation"]["excerpt"] == "第一条精选摘录"

    # 重命名 + 移除单项
    renamed = client.patch(
        f"/api/v1/annotation-baskets/{basket['id']}", json={"name": "引用清单"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "引用清单"
    removed = client.delete(
        f"/api/v1/annotation-baskets/{basket['id']}/items/{a1['id']}"
    )
    assert removed.status_code == 204
    after = client.get(f"/api/v1/annotation-baskets/{basket['id']}/items").json()
    assert [e["annotationId"] for e in after["items"]] == [a2["id"]]

    # 删除篮：成员关系级联删除，批注本体仍在
    deleted = client.delete(f"/api/v1/annotation-baskets/{basket['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/annotation-baskets").json()["items"] == []
    still = client.get(f"/api/v1/annotations?entryRef={ref}").json()
    assert a2["id"] in {item["id"] for item in still["items"]}

    missing = client.delete(f"/api/v1/annotation-baskets/{basket['id']}")
    assert missing.status_code == 404


def test_n072_export_filtered_by_basket(client):
    """导出走既有 export 路径：basketId 只含篮成员；互斥与 404 诚实。"""
    ref_a = encode_entry_ref("9202")
    ref_b = encode_entry_ref("9203")
    in_basket = _annotation(client, ref_a, "篮内摘录", 0)
    _annotation(client, ref_b, "篮外摘录", 1)

    basket = client.post("/api/v1/annotation-baskets", json={"name": "导出篮"}).json()
    client.post(
        f"/api/v1/annotation-baskets/{basket['id']}/items",
        json={"annotationIds": [in_basket["id"]]},
    )

    exported = client.post(
        "/api/v1/annotations/export", json={"basketId": basket["id"]}
    )
    assert exported.status_code == 200
    text = exported.text
    assert "篮内摘录" in text
    assert "篮外摘录" not in text

    # 互斥：basketId + q → 422
    conflict = client.post(
        "/api/v1/annotations/export", json={"basketId": basket["id"], "q": "x"}
    )
    assert conflict.status_code == 422
    # 未知篮 → 404
    missing = client.post(
        "/api/v1/annotations/export", json={"basketId": "no-such-basket"}
    )
    assert missing.status_code == 404


def test_n072_broken_marking_on_deleted_annotation_and_stale_anchor(client):
    """批注删除 → 成员行保留 broken=true annotation=null；
    锚点 stale → broken=true（诚实标注，不假装健在）。"""
    ref = encode_entry_ref("9204")
    deleted_one = _annotation(client, ref, "将被删除的摘录", 0)
    stale_one = _annotation(client, ref, "锚点漂移的摘录", 1)

    basket = client.post("/api/v1/annotation-baskets", json={"name": "诚实篮"}).json()
    client.post(
        f"/api/v1/annotation-baskets/{basket['id']}/items",
        json={"annotationIds": [deleted_one["id"], stale_one["id"]]},
    )

    # 删除批注本体
    assert client.delete(f"/api/v1/annotations/{deleted_one['id']}").status_code == 204
    # 锚点漂移（复用 N071 的 stale 语义：anchor.stale=true）
    async def mark_stale():
        from lumirss.annotation_store import AnnotationStore

        with user_context(app.state.owner_id):
            store = AnnotationStore(app.state.db)
            item = await store.get(stale_one["id"])
            anchor = dict(item["anchor"])
            anchor["stale"] = True
            import json as _json

            from lumirss.util import utc_now

            await app.state.db.execute(
                "UPDATE annotations SET anchor_json = ?, updated_at = ? WHERE id = ?",
                (_json.dumps(anchor, ensure_ascii=False), utc_now(), stale_one["id"]),
            )

    _run(mark_stale())

    entries = client.get(f"/api/v1/annotation-baskets/{basket['id']}/items").json()["items"]
    by_id = {e["annotationId"]: e for e in entries}
    assert by_id[deleted_one["id"]]["broken"] is True
    assert by_id[deleted_one["id"]]["annotation"] is None
    assert by_id[stale_one["id"]]["broken"] is True
    assert by_id[stale_one["id"]]["annotation"] is not None  # 本体还在，只是漂移

    # 导出：被删批注不出现在导出里（篮导出只含真实存在的成员）
    exported = client.post(
        "/api/v1/annotations/export", json={"basketId": basket["id"]}
    )
    assert exported.status_code == 200
    assert "锚点漂移的摘录" in exported.text
    assert "将被删除的摘录" not in exported.text


PASSWORD = None


def test_n072_cross_user_annotations_never_join(monkeypatch, tmp_path):
    """跨用户隔离（session 模式 + 真实 RoutingDatabase 路由）：

    A（owner）与 B（member）各自登录；B 建批注；A 的篮试图加入 B 的
    批注 id → skipped=annotation_not_found，绝不入篮。"""
    import secrets as _secrets

    from fastapi.testclient import TestClient

    password = _secrets.token_urlsafe(16)
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")

    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()

    async def _set_owner_password():
        from lumirss.accounts_store import AccountsStore, hash_password
        from lumirss.storage import Database

        database = Database(str(tmp_path / "lumi.sqlite"))
        await database.migrate()
        store = AccountsStore(database)
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                await store.set_password_hash(str(row["id"]), hash_password(password))
                return

    with TestClient(app, base_url="http://lumirss.test") as session_client:
        # owner 行由 lifespan 的 owner 迁移创建 —— 必须在启动后再设密码。
        _run(_set_owner_password())
        owner_login = session_client.post(
            "/api/v1/auth/login", json={"username": "owner", "password": password}
        )
        assert owner_login.status_code == 200
        owner = {"cookie": owner_login.headers["set-cookie"].split(";")[0]}
        invite = session_client.post(
            "/api/v1/admin/invites", json={"label": "n072b"}, headers=owner
        )
        activation = session_client.post(
            "/api/v1/auth/activate",
            json={"token": invite.json()["token"], "username": "n072b", "password": password},
        )
        assert activation.status_code == 200, activation.text
        member = {"cookie": activation.headers["set-cookie"].split(";")[0]}

        # B 建批注（进 B 的 per-user 库）
        created = session_client.post(
            "/api/v1/annotations",
            json={
                "entryRef": encode_entry_ref("9301"),
                "anchor": {"paraId": "p-0", "prefix": "", "exact": "B 的私有摘录", "suffix": ""},
                "excerpt": "B 的私有摘录",
                "note": "私有批注",
            },
            headers=member,
        )
        assert created.status_code == 201, created.text
        foreign_id = created.json()["id"]

        # A 建篮并试图加入 B 的批注
        basket = session_client.post(
            "/api/v1/annotation-baskets", json={"name": "A 的篮"}, headers=owner
        ).json()
        response = session_client.post(
            f"/api/v1/annotation-baskets/{basket['id']}/items",
            json={"annotationIds": [foreign_id]},
            headers=owner,
        )
        assert response.status_code == 200
        assert response.json()["added"] == []
        assert response.json()["skipped"] == [
            {"annotationId": foreign_id, "reason": "annotation_not_found"}
        ]
        items = session_client.get(
            f"/api/v1/annotation-baskets/{basket['id']}/items", headers=owner
        ).json()
        assert items["items"] == []
