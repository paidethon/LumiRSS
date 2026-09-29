"""NEW-241 文章更新差异阅读 — 显式版本保存 / 阅读 / 段落级差异 + 隔离。

- 保存两个版本 → 列表（新→旧）→ 阅读任一版全文 → diff：增加 / 删除 /
  修改段落计数真实；相似度不足的 replace 诚实拆成删+增；
- 校验：空标签 / 空正文 422；未知版本 diff 404；
- 隔离：per-user 库——A 的版本对 B 不可见（列表为空、diff 404）。
"""

from new231_helpers import ab_session


def test_new241_save_read_diff_paragraphs(client):
    """两版之间标出增/删/改段落；用户可阅读任一版本全文。"""
    ref = "e1.smoke-item"
    v1 = client.post(
        f"/api/v1/entries/{ref}/article-versions",
        json={"label": "保存时的版本", "contentText": "第一段不变。\n\n第二段要修改。\n\n第三段会被删除。\n"},
    )
    assert v1.status_code == 201, v1.text
    body = v1.json()
    assert body["origin"] == "manual"
    assert body["contentChars"] > 0

    v2 = client.post(
        f"/api/v1/entries/{ref}/article-versions",
        json={"label": "更新后的版本", "contentText": "第一段不变。\n\n第二段已修改完善。\n\n新增的第四段。\n"},
    )
    assert v2.status_code == 201, v2.text

    listed = client.get(f"/api/v1/entries/{ref}/article-versions")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert [i["label"] for i in items] == ["更新后的版本", "保存时的版本"]
    assert all("contentText" not in i for i in items)  # 列表不含正文

    # 阅读所选版本（全文）
    read = client.get(f"/api/v1/entries/{ref}/article-versions/{items[1]['id']}")
    assert read.status_code == 200
    assert "第三段会被删除。" in read.json()["contentText"]

    # diff：v1 → v2
    diff = client.get(
        f"/api/v1/entries/{ref}/article-versions/diff",
        params={"fromVersion": items[1]["id"], "toVersion": items[0]["id"]},
    )
    assert diff.status_code == 200, diff.text
    body = diff.json()
    assert body["identical"] is False
    assert body["modified"] >= 1  # 第二段：相似 → 修改
    assert body["removed"] >= 1  # 第三段：删除
    assert body["added"] >= 1  # 新增第四段
    kinds = {b["type"] for b in body["blocks"]}
    assert {"modified", "removed", "added"} <= kinds

    # 自身 diff → identical（诚实空差异）
    same = client.get(
        f"/api/v1/entries/{ref}/article-versions/diff",
        params={"fromVersion": items[0]["id"], "toVersion": items[0]["id"]},
    )
    assert same.status_code == 200
    assert same.json()["identical"] is True
    assert same.json()["added"] == 0


def test_new241_validation_and_missing(client):
    """空标签/空正文 422；未知版本 404。"""
    ref = "e1.smoke-item"
    bad_label = client.post(
        f"/api/v1/entries/{ref}/article-versions", json={"label": "", "contentText": "正文"}
    )
    assert bad_label.status_code == 422

    bad_content = client.post(
        f"/api/v1/entries/{ref}/article-versions", json={"label": "标签", "contentText": "  "}
    )
    assert bad_content.status_code == 422

    unknown = client.get(
        f"/api/v1/entries/{ref}/article-versions/diff",
        params={"fromVersion": "no-such", "toVersion": "no-such"},
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["type"] == "article_version_not_found"


def test_new241_isolation_between_users(monkeypatch, tmp_path):
    """A 保存的版本对 B 是 404 / 空列表（真实 RoutingDatabase per-user 库）。"""
    with ab_session(monkeypatch, tmp_path) as session:
        member = session.activate_member("n24x-b")
        ref = "e1.iso-item"
        saved = session.client.post(
            f"/api/v1/entries/{ref}/article-versions",
            json={"label": "A 的版本", "contentText": "A 保存的正文。"},
            headers=session.owner,
        )
        assert saved.status_code == 201, saved.text
        version_id = saved.json()["id"]

        # B：列表为空、读不到、diff 不到
        b_list = session.client.get(
            f"/api/v1/entries/{ref}/article-versions", headers=member
        )
        assert b_list.status_code == 200
        assert b_list.json()["items"] == []

        b_read = session.client.get(
            f"/api/v1/entries/{ref}/article-versions/{version_id}", headers=member
        )
        assert b_read.status_code == 404

        b_diff = session.client.get(
            f"/api/v1/entries/{ref}/article-versions/diff",
            params={"fromVersion": version_id, "toVersion": version_id},
            headers=member,
        )
        assert b_diff.status_code == 404

        # A 照常可见
        a_list = session.client.get(
            f"/api/v1/entries/{ref}/article-versions", headers=session.owner
        )
        assert len(a_list.json()["items"]) == 1
