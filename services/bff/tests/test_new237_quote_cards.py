"""NEW-237 引用卡片组装 — 预览 / 导出 / 来源索引 / 批注开关 / 隔离。

- 预览返回 markdown 全文 + 来源索引（[n] 标题—来源—日期 + 回原文链接，
  缺失项「不详」）；export 同构建、未知 id → 422（预览已如实上报）；
- includeNotes=false 不含批注；未知 id 在预览 honest skipped；
- 隔离：B 的批注 id 对 A 是 unknown。
"""

from lumirss.entryref import encode_entry_ref


def _annotation(client, entry_ref: str, excerpt: str, note: str | None) -> dict:
    response = client.post(
        "/api/v1/annotations",
        json={
            "entryRef": entry_ref,
            "anchor": {"paraId": "p-0", "exact": excerpt, "prefix": "", "suffix": ""},
            "excerpt": excerpt,
            "note": note,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_new237_preview_and_export_with_source_index(client):
    """几段引文 → 一张带来源索引的文字卡；预览与导出内容一致。"""
    ref_a = encode_entry_ref("10001")
    ref_b = encode_entry_ref("10002")
    a1 = _annotation(client, ref_a, "第一段引文", "我的第一条批注")
    b1 = _annotation(client, ref_b, "第二段引文", None)

    preview = client.post(
        "/api/v1/annotation-cards/preview",
        json={"annotationIds": [a1["id"], b1["id"]], "includeNotes": True, "title": "周报引用卡"},
    )
    assert preview.status_code == 200, preview.text
    card = preview.json()
    assert card["quoteCount"] == 2
    assert card["title"] == "周报引用卡"
    assert "第一段引文" in card["markdown"]
    assert "我的第一条批注" in card["markdown"]
    assert "[1]" in card["markdown"] and "[2]" in card["markdown"]
    assert len(card["sources"]) == 2
    assert card["sources"][0]["index"] == 1
    assert card["sources"][0]["backHref"].startswith(f"/reader?entry={ref_a}")
    assert card["unknownIds"] == []

    # includeNotes=false → 批注不出现
    plain = client.post(
        "/api/v1/annotation-cards/preview",
        json={"annotationIds": [a1["id"]], "includeNotes": False},
    )
    assert plain.status_code == 200
    assert "我的第一条批注" not in plain.json()["markdown"]
    assert "第一段引文" in plain.json()["markdown"]

    # 导出：Markdown 附件；内容与预览一致
    exported = client.post(
        "/api/v1/annotation-cards/export",
        json={"annotationIds": [a1["id"], b1["id"]], "includeNotes": True},
    )
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
    assert "第一段引文" in exported.text
    assert "来源索引" in exported.text

    # 空选择 → 422
    assert (
        client.post("/api/v1/annotation-cards/preview", json={"annotationIds": []}).status_code
        == 422
    )


def test_new237_unknown_ids_and_isolation(monkeypatch, tmp_path):
    """未知 id 预览 honest skipped；带未知 id 导出 422；B 的批注对 A
    是 unknown（per-user 隔离）。"""
    from new231_helpers import ab_session

    with ab_session(monkeypatch, tmp_path) as session:
        member = session.activate_member("n237b")
        foreign = session.client.post(
            "/api/v1/annotations",
            json={
                "entryRef": "10003",
                "anchor": {"paraId": "p-0", "exact": "B 的摘录", "suffix": ""},
                "excerpt": "B 的摘录",
                "note": "B 的批注",
            },
            headers=member,
        )
        assert foreign.status_code == 201
        foreign_id = foreign.json()["id"]

        mine = session.client.post(
            "/api/v1/annotations",
            json={
                "entryRef": "10004",
                "anchor": {"paraId": "p-0", "exact": "A 的摘录", "suffix": ""},
                "excerpt": "A 的摘录",
                "note": "A 的批注",
            },
            headers=session.owner,
        )
        assert mine.status_code == 201
        mine_id = mine.json()["id"]

        # 预览：B 的 id → unknown（诚实上报），A 的照常进卡
        preview = session.client.post(
            "/api/v1/annotation-cards/preview",
            json={"annotationIds": [mine_id, foreign_id]},
            headers=session.owner,
        )
        assert preview.status_code == 200
        body = preview.json()
        assert body["unknownIds"] == [foreign_id]
        assert body["quoteCount"] == 1
        assert "A 的摘录" in body["markdown"]
        assert "B 的摘录" not in body["markdown"]

        # 带未知 id 导出 → 422（防误操作）
        exported = session.client.post(
            "/api/v1/annotation-cards/export",
            json={"annotationIds": [mine_id, foreign_id]},
            headers=session.owner,
        )
        assert exported.status_code == 422
        assert exported.json()["error"]["type"] == "invalid_quote_card"
