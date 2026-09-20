"""F041 API 映射试跑强化 — atom_preview、错误映射、试跑零写入、头不回显。

Hermetic：上游 fetch 一律 monkeypatch（本仓库既有 fake 模式）。
"""

import asyncio

from lumirss.api_sources import (
    map_items,
    preview_atom_entries,
)

JSON_BODY = [
    {
        "id": "gh-1001",
        "title": "发布 v2.0 稳定版",
        "html_url": "https://example.com/r/1001",
        "published_at": "2026-09-01T08:30:00Z",
        "body": "<p>本次发布包含 <b>中文</b> 与 ISO 日期。</p>",
    },
    {
        "id": 1002,
        "title": "patch 1.1",
        "html_url": "https://example.com/r/1002",
        "published_at": "2026-08-15T00:00:00+08:00",
        "body": None,
    },
    {"id": "", "title": "无 id 的条目", "html_url": None, "published_at": "bad-date", "body": "x"},
    {"title": "缺 id", "html_url": None, "published_at": None, "body": None},
]

FIELD_MAP = {
    "id": "id",
    "title": "title",
    "url": "html_url",
    "published": "published_at",
    "body": "body",
}


def _run(coroutine):
    return asyncio.run(coroutine)


def test_f041_nested_extraction_and_preview_atom_shape():
    """嵌套数组抽取 + 前 3 条 Atom 最终形态（id/title/link/摘要/日期）。"""
    nested = {
        "data": {
            "releases": [
                {"meta": {"uid": "n-1"}, "name": "嵌套一", "url": "https://e.com/1",
                 "at": "2026-09-10T00:00:00Z", "html": "<p>正文一</p>"},
                {"meta": {"uid": "n-2"}, "name": "嵌套二", "url": "https://e.com/2",
                 "at": "2026-09-11T00:00:00Z", "html": "<p>正文二</p>"},
            ]
        }
    }
    items = map_items(
        nested,
        "data.releases[*]",
        {"id": "meta.uid", "title": "name", "url": "url", "published": "at", "body": "html"},
    )
    assert [i["id"] for i in items] == ["n-1", "n-2"]
    atom = preview_atom_entries(items)
    assert len(atom) == 2
    first = atom[0]
    assert first["id"].startswith("urn:lumirss:apisource:preview:")
    assert first["title"] == "嵌套一"
    assert first["link"] == "https://e.com/1"
    assert first["published"] == "2026-09-10T00:00:00+00:00"  # ISO → RFC 3339 归一
    assert first["contentExcerpt"] == "<p>正文一</p>"


def test_f041_empty_values_and_chinese_and_bad_dates():
    """空值字段诚实为 None/降级；中文标题保留；非法日期不出现在 published。"""
    items = map_items(JSON_BODY, "[*]", FIELD_MAP)
    # id 为空的条目被稳定 ID 校验排除（id/title 必须同时存在）
    assert len(items) == 2
    atom = preview_atom_entries(items)
    assert atom[0]["title"] == "发布 v2.0 稳定版"
    assert atom[0]["contentExcerpt"].startswith("<p>本次发布")
    # body=None → 摘要空串；published 带时区偏移被归一
    assert atom[1]["published"] == "2026-08-14T16:00:00+00:00"
    assert atom[1]["contentExcerpt"] == ""
    # 预览恒 ≤3 条
    many = [
        {"id": str(i), "title": f"t{i}", "published_at": "2026-09-01T00:00:00Z"}
        for i in range(10)
    ]
    assert len(preview_atom_entries(many)) == 3


def test_f041_invalid_jmespath_maps_to_422_envelope(client, monkeypatch):
    """非法 JMESPath → 422 + 明确错误信息（预览层错误族）。"""
    import lumirss.routers.api_sources as routes

    async def fake_fetch(client_arg, endpoint):
        return JSON_BODY

    monkeypatch.setattr(routes, "fetch_json", fake_fetch)
    response = client.post(
        "/api/v1/api-sources/preview",
        json={
            "endpoint": "https://api.example.com/x",
            "itemsExpr": "this is ][ not valid",
            "fieldMap": {"id": "id", "title": "title"},
        },
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["type"] in ("invalid_expression", "preview_expression_failed")
    assert "items 表达式" in error["message"] or "无法编译" in error["message"]


def test_f041_missing_stable_id_reports_validation_error(client, monkeypatch):
    """映射后无稳定 id/title → 校验错误（非静默空结果）。"""
    import lumirss.routers.api_sources as routes

    async def fake_fetch(client_arg, endpoint):
        return [{"name": "只有名字", "other": 1}]

    monkeypatch.setattr(routes, "fetch_json", fake_fetch)
    ok = client.post(
        "/api/v1/api-sources/preview",
        json={
            "endpoint": "https://api.example.com/x",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "name", "title": "name"},
        },
    )
    assert ok.status_code == 200
    assert ok.json()["totalAvailable"] == 1
    # 完全没有 id 字段表达式的映射在保存前即被拒
    bad = client.post(
        "/api/v1/api-sources/preview",
        json={
            "endpoint": "https://api.example.com/x",
            "itemsExpr": "[*]",
            "fieldMap": {"title": "name"},
        },
    )
    assert bad.status_code in (400, 422)


def test_f041_preview_writes_nothing_and_hides_upstream_headers(client, monkeypatch):
    """试跑零写入（store 无任何记录/变更）+ 响应模型不含上游 headers 字段。"""
    import lumirss.routers.api_sources as routes

    calls: list[str] = []

    async def fake_fetch(client_arg, endpoint):
        calls.append(endpoint)
        return JSON_BODY

    monkeypatch.setattr(routes, "fetch_json", fake_fetch)
    before = client.get("/api/v1/api-sources").json()["items"]
    response = client.post(
        "/api/v1/api-sources/preview",
        json={
            "endpoint": "https://api.example.com/x",
            "itemsExpr": "[*]",
            "fieldMap": FIELD_MAP,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["atomPreview"]) == 2  # 仅 id+title 双全的条目进入 Atom
    after = client.get("/api/v1/api-sources").json()["items"]
    assert before == after  # 零写入：列表无增无变
    # 负向断言：预览响应模型（OpenAPI schema）没有 headers 字段
    schema = client.get("/openapi.json").json()
    props = schema["components"]["schemas"]["ApiSourcePreviewResult"]["properties"]
    assert "headers" not in props
    assert "atomPreview" in props
