"""NEW-238 标注批量迁移 — 层间预览 / 应用 / 原文章身份不变 / 隔离。

- 预览零写入：展示每条的摘录/颜色与标签变化（fromLayer → toLayer）；
- 应用只改层归属；entryRef/anchor/正文零改动；
- 校验：同层 422；空集 422；层缺失 404；隔离：B 访问 A 的层 → 404。
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


def test_new238_preview_then_apply_between_layers(client):
    """未分层 → 层甲（全体），层甲 → 层乙（指定子集）；entryRef 不变。"""
    ref = encode_entry_ref("11001")
    a1 = _annotation(client, ref, "待归档摘录一", 0)
    a2 = _annotation(client, ref, "待归档摘录二", 1)
    a3 = _annotation(client, ref, "未分层摘录", 2)

    inbox = client.post("/api/v1/annotation-layers", json={"name": "收件箱层"}).json()
    archive = client.post("/api/v1/annotation-layers", json={"name": "归档层"}).json()

    # 未分层全体 → 收件箱层（预览）
    preview = client.post(
        "/api/v1/annotation-layers/migrate/preview",
        json={"fromLayerId": None, "toLayerId": inbox["id"]},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["fromLayer"] is None
    assert body["toLayer"] == "收件箱层"
    assert body["count"] == 3
    assert {item["annotationId"] for item in body["items"]} == {a1["id"], a2["id"], a3["id"]}
    assert all(item["toLayer"] == "收件箱层" for item in body["items"])

    # 应用 → 全部进入收件箱层；entryRef 不变
    applied = client.post(
        "/api/v1/annotation-layers/migrate/apply",
        json={"fromLayerId": None, "toLayerId": inbox["id"]},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["count"] == 3
    members = client.get(f"/api/v1/annotation-layers/{inbox['id']}/annotations").json()["items"]
    assert {item["id"] for item in members} == {a1["id"], a2["id"], a3["id"]}
    assert all(item["entryRef"] == ref for item in members)

    # 收件箱 → 归档（只迁 a1、a2）；标签变化（收件箱层 → 归档层）
    preview2 = client.post(
        "/api/v1/annotation-layers/migrate/preview",
        json={
            "fromLayerId": inbox["id"],
            "toLayerId": archive["id"],
            "annotationIds": [a1["id"], a2["id"]],
        },
    )
    assert preview2.status_code == 200
    body2 = preview2.json()
    assert body2["count"] == 2
    assert body2["fromLayer"] == "收件箱层"
    assert body2["toLayer"] == "归档层"

    applied2 = client.post(
        "/api/v1/annotation-layers/migrate/apply",
        json={
            "fromLayerId": inbox["id"],
            "toLayerId": archive["id"],
            "annotationIds": [a1["id"], a2["id"]],
        },
    )
    assert applied2.status_code == 200
    assert set(applied2.json()["moved"]) == {a1["id"], a2["id"]}

    archive_members = client.get(
        f"/api/v1/annotation-layers/{archive['id']}/annotations"
    ).json()["items"]
    assert {item["id"] for item in archive_members} == {a1["id"], a2["id"]}
    # 文章身份不变
    assert all(item["entryRef"] == ref for item in archive_members)
    detail_ids = {
        item["id"]: item for item in client.get(f"/api/v1/annotations?entryRef={ref}").json()["items"]
    }
    assert detail_ids[a1["id"]]["excerpt"] == "待归档摘录一"  # 正文/摘录未动

    # 同层 422；层缺失 404；空集 422
    fresh = _annotation(client, ref, "从未分层的摘录", 3)
    same = client.post(
        "/api/v1/annotation-layers/migrate/preview",
        json={"fromLayerId": archive["id"], "toLayerId": archive["id"]},
    )
    assert same.status_code == 422
    missing = client.post(
        "/api/v1/annotation-layers/migrate/preview",
        json={"fromLayerId": "no-such", "toLayerId": archive["id"]},
    )
    assert missing.status_code == 404
    missing_to = client.post(
        "/api/v1/annotation-layers/migrate/apply",
        json={"fromLayerId": archive["id"], "toLayerId": "no-such"},
    )
    assert missing_to.status_code == 404
    empty = client.post(
        "/api/v1/annotation-layers/migrate/apply",
        json={
            "fromLayerId": archive["id"],
            "toLayerId": inbox["id"],
            "annotationIds": [fresh["id"]],  # fresh 从未进归档层 → 来源集合为空
        },
    )
    assert empty.status_code == 422


def test_new238_cross_user_layers_isolated(monkeypatch, tmp_path):
    """B 看不到 A 的层：迁移引用 A 的层 → 404；A 的标注绝不进 B 的层。"""
    from new231_helpers import ab_session

    with ab_session(monkeypatch, tmp_path) as session:
        mine = session.client.post(
            "/api/v1/annotations",
            json={
                "entryRef": "11002",
                "anchor": {"paraId": "p-0", "exact": "A 的摘录", "suffix": ""},
                "excerpt": "A 的摘录",
                "note": "A 的批注",
            },
            headers=session.owner,
        ).json()
        target = session.client.post(
            "/api/v1/annotation-layers", json={"name": "A 的目标层"}, headers=session.owner
        ).json()
        member = session.activate_member("n238b")

        response = session.client.post(
            "/api/v1/annotation-layers/migrate/apply",
            json={
                "fromLayerId": None,
                "toLayerId": target["id"],
                "annotationIds": [mine["id"]],
            },
            headers=member,
        )
        assert response.status_code == 404  # toLayerId 是 A 的层，对 B 不存在
