"""NEW-250 证据完整性检查单 — 建单 / 三项证据状态 / 逐项补齐 + 隔离。

- 建单幂等（重复引文不重复建）；三项证据：source（来源指向）、
  version（保存版本，以 NEW-241 的已存版本为准——指向不存在的版本
  = honest missing）、excerpt（可定位片段）；缺项逐个 PATCH 补齐；
- 校验：空 citationRefs 422；空 PATCH 422；未知报告 404；
- 隔离：A 的检查单对 B 是 404（真实 RoutingDatabase per-user 库）。
"""

from new231_helpers import ab_session


def _save_version(client, entry_ref: str, label: str) -> dict:
    response = client.post(
        f"/api/v1/entries/{entry_ref}/article-versions",
        json={"label": label, "contentText": "证据版本的正文。"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_new250_checklist_fill_and_complete(client):
    """建单 → 三项全缺 → 逐项补齐（含真实保存版本）→ complete 计数。"""
    created = client.post(
        "/api/v1/evidence-checklists",
        json={"reportLabel": "九月综述", "citationRefs": ["c-1", "c-2", "c-1"]},
    )
    assert created.status_code == 201, created.text
    assert created.json()["citationRefs"] == ["c-1", "c-2"]  # 幂等去重

    report = client.get("/api/v1/evidence-checklists/九月综述")
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["total"] == 2
    assert body["completeCount"] == 0
    assert body["missingCount"] == 2
    first = body["items"][0]
    assert set(first["missing"]) == {"source", "version", "excerpt"}
    assert first["complete"] is False

    # c-1 逐项补齐：真实保存版本（NEW-241）+ 来源 + 片段
    version = _save_version(client, "e1.evidence-item", "保存的证据版本")
    patched = client.patch(
        "/api/v1/evidence-checklists/九月综述/items/c-1",
        json={"sourceRef": "rss:e1.evidence-item", "versionId": version["id"], "excerpt": "证据版本的正文。"},
    )
    assert patched.status_code == 200, patched.text
    item = patched.json()
    assert item["hasSource"] is True
    assert item["hasVersion"] is True
    assert item["versionExists"] is True
    assert item["hasExcerpt"] is True
    assert item["missing"] == []
    assert item["complete"] is True

    # 指向不存在的版本 = honest missing（不冒充已具备）
    patched2 = client.patch(
        "/api/v1/evidence-checklists/九月综述/items/c-2",
        json={"versionId": "no-such-version", "sourceRef": "rss:e1.x"},
    )
    assert patched2.status_code == 200
    item2 = patched2.json()
    assert item2["hasVersion"] is False
    assert item2["versionExists"] is False
    assert "version" in item2["missing"]

    after = client.get("/api/v1/evidence-checklists/九月综述").json()
    assert after["completeCount"] == 1
    assert after["missingCount"] == 1


def test_new250_validation_and_missing(client):
    empty_refs = client.post(
        "/api/v1/evidence-checklists", json={"reportLabel": "报告", "citationRefs": []}
    )
    assert empty_refs.status_code == 422

    empty_patch = client.patch(
        "/api/v1/evidence-checklists/报告/items/c-1", json={}
    )
    assert empty_patch.status_code == 422

    unknown_report = client.get("/api/v1/evidence-checklists/不存在的报告")
    assert unknown_report.status_code == 404
    assert unknown_report.json()["error"]["type"] == "evidence_not_found"

    # 先建后补：PATCH 未登记的引文 → 404
    client.post(
        "/api/v1/evidence-checklists", json={"reportLabel": "报告2", "citationRefs": ["c-9"]}
    )
    missing_item = client.patch(
        "/api/v1/evidence-checklists/报告2/items/c-other", json={"excerpt": "片段"}
    )
    assert missing_item.status_code == 404


def test_new250_isolation_between_users(monkeypatch, tmp_path):
    """A 的检查单对 B 是 404（真实 RoutingDatabase per-user 库）。"""
    with ab_session(monkeypatch, tmp_path) as session:
        member = session.activate_member("n24x-b")
        created = session.client.post(
            "/api/v1/evidence-checklists",
            json={"reportLabel": "A 的报告", "citationRefs": ["c-1"]},
            headers=session.owner,
        )
        assert created.status_code == 201, created.text

        b_report = session.client.get(
            "/api/v1/evidence-checklists/A 的报告", headers=member
        )
        assert b_report.status_code == 404

        b_patch = session.client.patch(
            "/api/v1/evidence-checklists/A 的报告/items/c-1", json={"excerpt": "B 的补齐"}
        )
        assert b_patch.status_code == 404

        a_report = session.client.get(
            "/api/v1/evidence-checklists/A 的报告", headers=session.owner
        )
        assert a_report.status_code == 200
        assert a_report.json()["total"] == 1
