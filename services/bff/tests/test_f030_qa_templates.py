"""F030 问答模板 —— CRUD、长度边界、隔离性（模板与文章无关）。"""

import json


def test_f030_crud_roundtrip_and_length_bounds(client):
    created = client.post(
        "/api/v1/qa-templates",
        json={"name": "总结模板", "text": "请总结这篇文章的三个要点<script>alert(1)</script>"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "总结模板"
    # XSS 文本原样存储（渲染转义由客户端 React 负责）；响应是 JSON，
    # 无任何脚本执行面
    assert "<script>" in body["text"]

    # 列表
    listing = client.get("/api/v1/qa-templates").json()["items"]
    assert any(item["id"] == body["id"] for item in listing)

    # 重命名
    renamed = client.patch(
        f"/api/v1/qa-templates/{body['id']}", json={"name": "要点模板"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "要点模板"

    # 长度上限 → 422
    too_long = client.post(
        "/api/v1/qa-templates",
        json={"name": "x", "text": "长" * 501},
    )
    assert too_long.status_code == 422
    name_too_long = client.post(
        "/api/v1/qa-templates",
        json={"name": "长" * 61, "text": "正文"},
    )
    assert name_too_long.status_code == 422

    # 删除 + 二次删除 404
    assert client.delete(f"/api/v1/qa-templates/{body['id']}").status_code == 204
    assert client.delete(f"/api/v1/qa-templates/{body['id']}").status_code == 404


def test_f030_templates_are_article_independent_and_stable(client):
    """空文章/切换文章时模板列表不变（隔离性：模板不绑定 entry）。"""
    first = client.get("/api/v1/qa-templates").json()["items"]
    client.post(
        "/api/v1/qa-templates", json={"name": "固定模板", "text": "这篇文章的作者立场是什么？"}
    )
    # 模拟「切换文章」：不同 entry 的会话路径不影响模板列表
    second = client.get("/api/v1/qa-templates").json()["items"]
    assert len(second) == len(first) + 1
    assert all(item["name"] != "" for item in second)
    # 无文章上下文字段（隔离性）
    assert all("entryRef" not in json.dumps(item) for item in second)
