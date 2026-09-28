"""NEW-234 个人批注层 — CRUD / 成员 / 按层读取与导出 / 删层回未分层 / 隔离。

- 层是纯个人结构；删层把成员批注回未分层（本体不删）；
- 未知批注 honest skipped；重复加入 already_in_layer；
- 导出 includeNotes 开关；隔离：A 无法把 B 的批注加进 A 的层。
"""

from lumirss.entryref import encode_entry_ref


def _annotation(client, entry_ref: str, excerpt: str, marker: int) -> dict:
    response = client.post(
        "/api/v1/annotations",
        json={
            "entryRef": entry_ref,
            "anchor": {"paraId": f"p-{marker}", "exact": excerpt, "prefix": "", "suffix": ""},
            "excerpt": excerpt,
            "note": f"批注 {marker}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_new234_layer_crud_members_and_export(client):
    """建层 → 加入 → 按层读取 → 导出（含/不含批注）→ 移除 → 删层回未分层。"""
    ref = encode_entry_ref("9801")
    a1 = _annotation(client, ref, "精读摘录一", 0)
    a2 = _annotation(client, ref, "精读摘录二", 1)
    stray = _annotation(client, ref, "未分层摘录", 2)

    created = client.post("/api/v1/annotation-layers", json={"name": "精读考据"})
    assert created.status_code == 201, created.text
    layer = created.json()
    assert layer["name"] == "精读考据"
    assert layer["itemCount"] == 0

    # 空名 → 422
    assert client.post("/api/v1/annotation-layers", json={"name": "  "}).status_code == 422

    # 加入（未知批注 honest skipped）
    added = client.post(
        f"/api/v1/annotation-layers/{layer['id']}/items",
        json={"annotationIds": [a1["id"], a2["id"], "nonexistent"]},
    )
    assert added.status_code == 200, added.text
    assert added.json()["added"] == [a1["id"], a2["id"]]
    assert added.json()["skipped"] == [
        {"annotationId": "nonexistent", "reason": "annotation_not_found"}
    ]

    # 幂等：重复加入 → already_in_layer
    again = client.post(
        f"/api/v1/annotation-layers/{layer['id']}/items",
        json={"annotationIds": [a1["id"]]},
    )
    assert again.json()["added"] == []
    assert again.json()["skipped"] == [
        {"annotationId": a1["id"], "reason": "already_in_layer"}
    ]

    # 层列表计数
    layers = client.get("/api/v1/annotation-layers").json()["items"]
    assert len(layers) == 1
    assert layers[0]["itemCount"] == 2

    # 按层读取（切换批注层的读取面）：只含成员
    members = client.get(f"/api/v1/annotation-layers/{layer['id']}/annotations").json()
    assert {item["id"] for item in members["items"]} == {a1["id"], a2["id"]}
    assert all(item["layerId"] == layer["id"] for item in members["items"])

    # 导出（含批注 / 不含批注）
    export = client.post(
        f"/api/v1/annotation-layers/{layer['id']}/export", json={"includeNotes": True}
    )
    assert export.status_code == 200
    text = export.text
    assert "批注层：精读考据" in text
    assert "精读摘录一" in text
    assert "批注 0" in text  # 我的批注
    assert f"/reader?entry={ref}" in text
    export_plain = client.post(
        f"/api/v1/annotation-layers/{layer['id']}/export", json={"includeNotes": False}
    )
    assert "批注 0" not in export_plain.text
    assert "精读摘录一" in export_plain.text

    # 移除单项 → 回未分层
    removed = client.delete(f"/api/v1/annotation-layers/{layer['id']}/items/{a1['id']}")
    assert removed.status_code == 204
    members = client.get(f"/api/v1/annotation-layers/{layer['id']}/annotations").json()
    assert {item["id"] for item in members["items"]} == {a2["id"]}

    # 删层 → a2 回未分层（本体仍在），层消失
    deleted = client.delete(f"/api/v1/annotation-layers/{layer['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/annotation-layers").json()["items"] == []
    listing = client.get(f"/api/v1/annotations?entryRef={ref}").json()
    ids = {item["id"] for item in listing["items"]}
    assert ids == {a1["id"], a2["id"], stray["id"]}
    # 三条批注都回到未分层：未分层迁移预览可见全体（诚实核对 layer_id=NULL）
    probe_layer = client.post("/api/v1/annotation-layers", json={"name": "探针层"}).json()
    unassigned = client.post(
        "/api/v1/annotation-layers/migrate/preview",
        json={"fromLayerId": None, "toLayerId": probe_layer["id"]},
    )
    assert unassigned.status_code == 200
    assert {item["annotationId"] for item in unassigned.json()["items"]} == ids
    client.delete(f"/api/v1/annotation-layers/{probe_layer['id']}")

    # 未知层 → 404
    assert client.delete("/api/v1/annotation-layers/no-such").status_code == 404
    assert client.get("/api/v1/annotation-layers/no-such/annotations").status_code == 404


def test_new234_cross_user_layers_isolated(monkeypatch, tmp_path):
    """A 无法把 B 的批注加入 A 的层（skipped annotation_not_found）；
    B 看不到 A 的层（404）。"""
    from new231_helpers import ab_session

    with ab_session(monkeypatch, tmp_path) as session:
        owner_layer = session.client.post(
            "/api/v1/annotation-layers", json={"name": "A 的层"}, headers=session.owner
        )
        assert owner_layer.status_code == 201
        layer_id = owner_layer.json()["id"]

        member = session.activate_member("n234b")
        foreign = session.client.post(
            "/api/v1/annotations",
            json={
                "entryRef": "9803",
                "anchor": {"paraId": "p-0", "exact": "B 的私有摘录", "suffix": ""},
                "excerpt": "B 的私有摘录",
                "note": "B 的批注",
            },
            headers=member,
        )
        assert foreign.status_code == 201, foreign.text
        foreign_id = foreign.json()["id"]

        # A 的层加入 B 的批注 → skipped（per-user 库里该 id 不存在）
        added = session.client.post(
            f"/api/v1/annotation-layers/{layer_id}/items",
            json={"annotationIds": [foreign_id]},
            headers=session.owner,
        )
        assert added.status_code == 200
        assert added.json()["added"] == []
        assert added.json()["skipped"] == [
            {"annotationId": foreign_id, "reason": "annotation_not_found"}
        ]

        # B 访问 A 的层 → 404
        assert (
            session.client.get(
                f"/api/v1/annotation-layers/{layer_id}/annotations", headers=member
            ).status_code
            == 404
        )
        # B 的层列表为空
        assert session.client.get(
            "/api/v1/annotation-layers", headers=member
        ).json()["items"] == []
