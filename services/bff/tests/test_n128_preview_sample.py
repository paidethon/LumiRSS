"""N128 API 字段映射向导（离线样例）— POST /api/v1/api-sources/preview-sample.

Proves the pasted-sample preview runs the SAME mapping + Atom-preview
pipeline as the live preview (identical response shape + an honest
sampleMode marker), handles the three sample classes honestly (date
field, missing field → validation error surfaced, array-of-objects),
and never stores or echoes anything (no network, no headers, no rows).
"""

import asyncio


def _run(coroutine):
    return asyncio.run(coroutine)


SAMPLE_ARRAY = [
    {
        "id": 7,
        "name": "v1.0 <稳定版>",
        "html_url": "https://example.com/r/7",
        "published_at": "2026-09-01T00:00:00Z",
        "body": "<p>发布说明</p>",
    },
    {
        "id": 6,
        "name": "v0.9",
        "html_url": "https://example.com/r/6",
        "published_at": "2026-08-01T00:00:00+00:00",
        "body": "旧版本",
    },
]

FIELD_MAP = {
    "id": "id",
    "title": "name",
    "url": "html_url",
    "published": "published_at",
    "body": "body",
}


def test_sample_date_field_maps_to_rfc3339(client):
    response = client.post(
        "/api/v1/api-sources/preview-sample",
        json={"samplePayload": SAMPLE_ARRAY, "itemsExpr": "[*]", "fieldMap": FIELD_MAP},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sampleMode"] is True
    assert body["totalAvailable"] == 2
    # 日期字段诚实呈现：映射结果保留原值，Atom 管线归一化为 RFC 3339 UTC
    assert body["items"][0]["published"] == "2026-09-01T00:00:00Z"
    assert body["items"][1]["published"] == "2026-08-01T00:00:00+00:00"
    assert body["atomPreview"][0]["published"] == "2026-09-01T00:00:00+00:00"
    assert body["atomPreview"][1]["published"] == "2026-08-01T00:00:00+00:00"
    # 不可解析的日期 → 诚实 null（绝不编造）
    bad_date = client.post(
        "/api/v1/api-sources/preview-sample",
        json={
            "samplePayload": [{"id": 1, "name": "x", "published": "not-a-date"}],
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "name", "published": "published"},
        },
    )
    assert bad_date.status_code == 200
    assert bad_date.json()["items"][0]["published"] == "not-a-date"
    assert bad_date.json()["atomPreview"][0]["published"] is None


def test_sample_array_of_objects_root_and_nested_items_expr(client):
    # 根数组
    ok = client.post(
        "/api/v1/api-sources/preview-sample",
        json={
            "samplePayload": SAMPLE_ARRAY,
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "name"},
        },
    )
    assert ok.status_code == 200
    assert ok.json()["totalAvailable"] == 2
    # 对象根 + 数组字段（items）
    nested = client.post(
        "/api/v1/api-sources/preview-sample",
        json={
            "samplePayload": {"items": SAMPLE_ARRAY},
            "itemsExpr": "items",
            "fieldMap": {"id": "id", "title": "name"},
        },
    )
    assert nested.status_code == 200
    assert nested.json()["totalAvailable"] == 2


def test_sample_missing_required_field_surfaces_validation_error(client):
    """缺字段类样例：映射不出 id/title → 稳定 422，绝不编造数据。"""
    sparse = [{"name": "只有名字，没有 id"}, {"name": "同样没有"}]
    response = client.post(
        "/api/v1/api-sources/preview-sample",
        json={
            "samplePayload": sparse,
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "name"},
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["type"] == "preview_expression_failed"
    assert "为空" in response.json()["error"]["message"]


def test_sample_bad_expression_is_stable_error_not_500(client):
    response = client.post(
        "/api/v1/api-sources/preview-sample",
        json={
            "samplePayload": SAMPLE_ARRAY,
            "itemsExpr": "this is ][ not valid",
            "fieldMap": FIELD_MAP,
        },
    )
    # 编译期即失败：稳定 invalid_expression（400），与全站表达式错误同族
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_expression"


def test_sample_response_shape_matches_live_preview(client):
    """响应形状与在线预览一致（多出的唯一字段是诚实的 sampleMode）。"""
    live = client.post(
        "/api/v1/api-sources/preview",
        json={
            "endpoint": "https://allowlist.example/api",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "name"},
        },
    )
    sample = client.post(
        "/api/v1/api-sources/preview-sample",
        json={
            "samplePayload": SAMPLE_ARRAY,
            "itemsExpr": "[*]",
            "fieldMap": FIELD_MAP,
        },
    )
    assert sample.status_code == 200
    sample_keys = set(sample.json().keys())
    if live.status_code == 200:
        assert sample_keys == set(live.json().keys()) | {"sampleMode"}
    else:
        # live 预览在无网络桩时失败（连接错误 502），仅校验样例键
        assert sample_keys == {
            "items",
            "totalAvailable",
            "atomPreview",
            "paginationDryRun",
            "sampleMode",
        }
    # atomPreview 与在线管线同构（urn id / RFC3339 / 摘要）
    entry = sample.json()["atomPreview"][0]
    assert entry["id"].startswith("urn:lumirss:apisource:preview:")
    assert entry["published"] is not None
    assert set(entry.keys()) == {
        "id",
        "title",
        "link",
        "published",
        "updated",
        "contentExcerpt",
    }


def test_sample_mode_is_offline_and_stores_nothing(client):
    """无网络、无头、无落库：不创建 api_sources 行，响应无任何 header 回显。"""
    import lumirss.routers.api_sources as routes

    async def _fail_fetch(*args, **kwargs):
        raise AssertionError("preview-sample 必须零网络：不应发起任何 fetch")

    original = routes.fetch_json
    routes.fetch_json = _fail_fetch
    try:
        response = client.post(
            "/api/v1/api-sources/preview-sample",
            json={
                "samplePayload": SAMPLE_ARRAY,
                "itemsExpr": "[*]",
                "fieldMap": FIELD_MAP,
            },
        )
    finally:
        routes.fetch_json = original
    assert response.status_code == 200
    text = response.text.lower()
    for header_like in ("authorization", "cookie", "x-api-key", "retry-after"):
        assert header_like not in text

    import os

    from lumirss.api_source_store import ApiSourceStore
    from lumirss.storage import Database

    db = Database(os.environ["LUMIRSS_DB_PATH"])
    rows = _run(ApiSourceStore(db).list_sources())
    assert rows == []  # 样例预览绝不落库
