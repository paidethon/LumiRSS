"""F39 Lumi 数据可携带导出 — 形状、边界与排除项。"""

import json


def test_export_contains_owned_domains_only(client):
    # 种子：工作区（含说明）+ 书签（RSS 引用）+ 标签绑定 + 日报配置/期刊
    assert (
        client.post(
            "/api/v1/workspaces",
            json={"name": "导出测试", "description": "F39 说明"},
        ).status_code
        == 201
    )
    entry_ref = "e1.MDAwNjU5ZTA3YWFlZTI0ZA"
    assert (
        client.post(
            "/api/v1/library/bookmarks",
            json={"rssItemRef": f"rss:{entry_ref}", "title": "笔记", "note": "要点"},
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/gpt-digest/configs",
            json={"name": "导出日报", "slots": [8, 20]},
        ).status_code
        == 201
    )

    response = client.get("/api/v1/export/lumi-data")
    assert response.status_code == 200
    assert "attachment" in response.headers.get("content-disposition", "")
    data = json.loads(response.content)

    assert data["kind"] == "lumirss-lumi-data"
    assert data["schemaVersion"] == 1
    workspace = next(w for w in data["workspaces"] if w["name"] == "导出测试")
    assert workspace["description"] == "F39 说明"
    assert data["bookmarks"][0]["note"] == "要点"
    created_config = next(c for c in data["digestConfigs"] if c["name"] == "导出日报")
    assert created_config["slots"] == [8, 20]
    # 密钥/token 绝不出现（订阅 token 存 secrets，不在 SQLite 导出域）
    assert "token" not in response.text.lower()
    # Vault / Agent / FreshRSS 订阅不在导出域
    text = response.text
    assert "vaultPath" not in text
    assert "approvals" not in text
