"""N117 工作区模板承载布局测试 —— includeStructure（组/分节/看板列/收集规则）。

- 模板创建带 includeStructure=true → config.structure 快照（组顺序 +
  分节大纲 + 看板状态列 + 收集规则条件；绝无条目内容/引用）；
- 应用 → 新工作区恢复「空壳结构」：分节空壳、组序（groupOrder 回显）、
  收集规则重建（addedCount=0）；条目内容绝不复制；
- includeStructure=false → 与 F083 原行为完全一致（config 无 structure）。
"""

import json

import pytest


@pytest.fixture()
def structured_workspace(client):
    """带结构的工作区：两个命名组（各有成员——组必须真实存在才能进
    顺序）+ 两个分节 + 一条收集规则。"""
    created = client.post("/api/v1/workspaces", json={"name": "模板源"})
    workspace_id = created.json()["id"]
    for index, group in enumerate(["甲组", "乙组"]):
        ref = client.post(
            "/api/v1/library/bookmarks",
            json={
                "url": f"https://example.com/n117-src-{index}",
                "title": f"源条目{index}",
            },
        ).json()["ref"]
        added = client.post(
            f"/api/v1/workspaces/{workspace_id}/items",
            json={"itemRef": ref, "groupName": group},
        )
        assert added.status_code == 201
    ordered = client.put(
        f"/api/v1/workspaces/{workspace_id}/groups",
        json={"order": ["甲组", "乙组"]},
    )
    assert ordered.status_code == 200
    client.post(
        f"/api/v1/workspaces/{workspace_id}/sections", json={"title": "背景"}
    )
    client.post(
        f"/api/v1/workspaces/{workspace_id}/sections", json={"title": "方法"}
    )
    rule = client.post(
        f"/api/v1/workspaces/{workspace_id}/collect-rules",
        json={"keyword": "检索", "maxItems": 10},
    )
    assert rule.status_code == 201
    return workspace_id


def test_template_with_structure_carries_layout(client, structured_workspace):
    response = client.post(
        f"/api/v1/workspaces/{structured_workspace}/save-as-template",
        json={"name": "研究模板", "includeStructure": True},
    )
    assert response.status_code == 201
    template = response.json()
    structure = template["config"]["structure"]
    assert structure["groupOrder"] == ["甲组", "乙组"]
    assert [s["title"] for s in structure["sections"]] == ["背景", "方法"]
    assert structure["boardColumns"] == [
        "todo", "reading", "excerpted", "needs_verification", "done"
    ]
    assert structure["collectRules"] == [
        {"feedUrl": None, "tag": None, "keyword": "检索", "maxItems": 10, "enabled": True}
    ]
    # 结构快照绝不携带条目内容/引用。
    blob = json.dumps(template, ensure_ascii=False)
    assert "library:" not in blob
    assert "源条目" not in blob


def test_apply_restores_empty_shells_without_content(
    client, structured_workspace
):
    template = client.post(
        f"/api/v1/workspaces/{structured_workspace}/save-as-template",
        json={"name": "结构模板", "includeStructure": True},
    ).json()
    result = client.post(
        "/api/v1/workspaces/from-template",
        json={
            "templateId": template["id"],
            "name": "新工作区",
            "includeStructure": True,
        },
    )
    assert result.status_code == 201
    body = result.json()
    new_id = body["workspace"]["id"]
    assert new_id != structured_workspace
    assert body["structure"]["sectionsCreated"] == 2
    assert body["structure"]["groupOrderRestored"] == 2
    assert body["structure"]["collectRulesCreated"] == 1

    # 空壳分节：存在、标题一致、成员为空。
    sections = client.get(f"/api/v1/workspaces/{new_id}/sections").json()["items"]
    assert [s["title"] for s in sections] == ["背景", "方法"]
    assert all(s["items"] == [] for s in sections)

    # 空壳组序：groupOrder 回显模板顺序（成员加入同名组后自然显形）。
    groups = client.get(f"/api/v1/workspaces/{new_id}/groups").json()
    assert groups["groupOrder"] == ["甲组", "乙组"]

    # 收集规则重建：条件一致、addedCount 归零。
    rules = client.get(f"/api/v1/workspaces/{new_id}/collect-rules").json()["items"]
    assert len(rules) == 1
    assert rules[0]["keyword"] == "检索"
    assert rules[0]["maxItems"] == 10
    assert rules[0]["addedCount"] == 0

    # 内容绝不复制：新工作区 0 成员。
    members = client.get(
        f"/api/v1/workspaces/{new_id}/items", params={"limit": 500}
    ).json()["items"]
    assert members == []
    assert body["workspace"]["itemCount"] == 0


def test_without_structure_flag_behavior_unchanged(client, structured_workspace):
    template = client.post(
        f"/api/v1/workspaces/{structured_workspace}/save-as-template",
        json={"name": "朴素模板"},
    ).json()
    assert "structure" not in template["config"]
    result = client.post(
        "/api/v1/workspaces/from-template",
        json={"templateId": template["id"], "name": "朴素新工作区"},
    )
    assert result.status_code == 201
    assert result.json()["structure"] is None
