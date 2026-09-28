"""NEW-232 失效标注重定位 — 手动重锚 / 旧位置历史 / 冲突 / 隔离。

- 重锚：anchor 更新 + 旧锚点/旧摘录进 append-only 历史（永不覆盖）；
- 可选新摘录；不给 → 旧摘录原样保留；
- 校验：空 anchor/缺 paraId 422；未知批注 404；新锚点与他条冲突 409；
- 隔离：B 不能重锚 A 的批注（404）。
"""

from lumirss.entryref import encode_entry_ref


def _annotation(client, entry_ref: str, excerpt: str, marker: int) -> dict:
    response = client.post(
        "/api/v1/annotations",
        json={
            "entryRef": entry_ref,
            "anchor": {"paraId": f"block-{marker}", "prefix": "", "exact": excerpt, "suffix": ""},
            "excerpt": excerpt,
            "note": f"批注 {marker}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_new232_reanchor_preserves_old_quote_and_position(client):
    """手动重锚：旧引文与旧位置先进历史再改本体；history 永久保留。"""
    ref = encode_entry_ref("9401")
    item = _annotation(client, ref, "原文更新前的旧摘录", 0)
    old_hash = item["anchorHash"]

    reanchored = client.post(
        f"/api/v1/annotations/{item['id']}/re-anchor",
        json={"anchor": {"paraId": "block-7", "exact": "更新后的新段落文本"}},
    )
    assert reanchored.status_code == 200, reanchored.text
    body = reanchored.json()
    assert body["anchor"]["paraId"] == "block-7"
    assert body["anchor"]["exact"] == "更新后的新段落文本"
    # 未给新摘录 → 旧摘录原样保留（重定位不改文字）
    assert body["excerpt"] == "原文更新前的旧摘录"
    assert body["anchorHash"] != old_hash

    # 历史：一条记录，含旧锚点与旧摘录（旧位置可追溯）
    history = client.get(f"/api/v1/annotations/{item['id']}/re-anchor-history")
    assert history.status_code == 200
    entries = history.json()["items"]
    assert len(entries) == 1
    assert entries[0]["oldExcerpt"] == "原文更新前的旧摘录"
    assert entries[0]["oldAnchor"]["paraId"] == "block-0"
    assert entries[0]["newAnchor"]["paraId"] == "block-7"
    assert entries[0]["source"] == "manual"

    # 再次重锚（带新摘录）→ 历史追加（append-only，不覆盖）
    again = client.post(
        f"/api/v1/annotations/{item['id']}/re-anchor",
        json={"anchor": {"paraId": "block-9"}, "excerpt": "第二次手动选中的摘录"},
    )
    assert again.status_code == 200
    assert again.json()["excerpt"] == "第二次手动选中的摘录"
    entries = client.get(f"/api/v1/annotations/{item['id']}/re-anchor-history").json()["items"]
    assert len(entries) == 2
    assert entries[1]["oldExcerpt"] == "原文更新前的旧摘录"  # 最旧的仍在


def test_new232_validation_and_conflict(client):
    """空 anchor / 缺 paraId → 422；未知批注 → 404；新锚点与他条 hash
    冲突 → 409（绝不覆盖既有批注的幂等键）。"""
    ref = encode_entry_ref("9402")
    a1 = _annotation(client, ref, "摘录甲", 0)
    _annotation(client, ref, "摘录乙", 1)

    empty = client.post(
        f"/api/v1/annotations/{a1['id']}/re-anchor", json={"anchor": {}}
    )
    assert empty.status_code == 422
    assert empty.json()["error"]["type"] == "invalid_reanchor"

    no_para = client.post(
        f"/api/v1/annotations/{a1['id']}/re-anchor",
        json={"anchor": {"exact": "没有段落定位"}},
    )
    assert no_para.status_code == 422

    missing = client.post(
        "/api/v1/annotations/no-such/re-anchor",
        json={"anchor": {"paraId": "block-1"}},
    )
    assert missing.status_code == 404

    # a1 重锚到 a2 的锚点（同 entryRef + 同 paraId/exact）→ hash 冲突 409
    clash = client.post(
        f"/api/v1/annotations/{a1['id']}/re-anchor",
        json={"anchor": {"paraId": "block-1", "exact": "摘录乙"}},
    )
    assert clash.status_code == 409
    assert clash.json()["error"]["type"] == "anchor_conflict"


def test_new232_cross_user_reanchor_isolated(monkeypatch, tmp_path):
    """A/B 隔离：B 不能重锚 A 的批注，也看不到 A 的重锚历史（404）。"""
    from new231_helpers import ab_session

    with ab_session(monkeypatch, tmp_path) as session:
        created = session.client.post(
            "/api/v1/annotations",
            json={
                "entryRef": "9403",
                "anchor": {"paraId": "block-0", "exact": "A 的私有摘录", "suffix": ""},
                "excerpt": "A 的私有摘录",
                "note": "私有批注",
            },
            headers=session.owner,
        )
        assert created.status_code == 201, created.text
        annotation_id = created.json()["id"]
        member = session.activate_member("n232b")

        response = session.client.post(
            f"/api/v1/annotations/{annotation_id}/re-anchor",
            json={"anchor": {"paraId": "block-5"}},
            headers=member,
        )
        assert response.status_code == 404
        history = session.client.get(
            f"/api/v1/annotations/{annotation_id}/re-anchor-history", headers=member
        )
        assert history.status_code == 404
