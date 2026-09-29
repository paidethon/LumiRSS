"""NEW-301 API 字段映射编辑器 — 样本/试映射预览/绑定 + A/B 隔离。"""

import asyncio

import pytest

from lumirss.api_source_store import ApiSourceStore
from lumirss.new301_mapping_samples import (
    MappingSampleStore,
    SampleInvalid,
    preview_sample_mapping,
)
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册


def _run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture()
def source_db(tmp_path):
    from lumirss.storage import Database

    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    return db


SAMPLE = {
    "data": {
        "list": [
            {"uid": 7, "heading": "v1.0 <稳定版>", "html": "<p>正文 &amp; 更多</p>",
             "ts": "2026-09-01T00:00:00Z", "link": "https://example.com/r/7"},
            {"uid": 6, "heading": "v0.9", "html": "旧版本",
             "ts": "2026-08-01T00:00:00Z", "link": "https://example.com/r/6"},
        ]
    }
}

TRIAL_MAP = {
    "id": "uid",
    "title": "heading",
    "body": "html",
    "published": "ts",
    "url": "link",
}


def test_new301_preview_uses_production_pipeline(source_db):
    """预览走与生产相同的 map_items 管线：字段值/总数一致，零写入。"""
    store = MappingSampleStore(source_db)
    created = _run(store.save_sample("src-1", "首发样本", SAMPLE))
    result = preview_sample_mapping(
        created["sampleJson"], TRIAL_MAP, "data.list[*]"
    )
    assert result["totalAvailable"] == 2
    assert result["items"][0]["title"] == "v1.0 <稳定版>"
    assert result["items"][0]["id"] == 7
    # 预览不落任何来源配置
    assert _run(ApiSourceStore(source_db).list_sources()) == []


def test_new301_preview_rejects_bad_mapping(source_db):
    store = MappingSampleStore(source_db)
    created = _run(store.save_sample("src-1", "样本", SAMPLE))
    with pytest.raises(SampleInvalid):
        preview_sample_mapping(
            created["sampleJson"],
            {"id": "uid", "title": "heading[[x"},
            "data.list[*]",
        )
    with pytest.raises(SampleInvalid):
        preview_sample_mapping(
            created["sampleJson"], {"title": "heading"}, "data.list[*]"
        )  # 缺 id
    with pytest.raises(SampleInvalid):
        preview_sample_mapping("not json {", TRIAL_MAP, "data.list[*]")


def test_new301_sample_bounds(source_db):
    store = MappingSampleStore(source_db)
    for index in range(10):
        _run(store.save_sample("src-1", f"样本{index}", SAMPLE))
    with pytest.raises(SampleInvalid):
        _run(store.save_sample("src-1", "第十一份", SAMPLE))
    with pytest.raises(SampleInvalid):
        _run(store.save_sample("src-1", "超大", {"blob": "x" * (300 * 1024)}))
    with pytest.raises(SampleInvalid):
        _run(store.save_sample("src-1", "   ", SAMPLE))


def test_new301_bind_updates_existing_source(client, monkeypatch):
    """绑定 = 既有 update 语义：fieldMap 更新 + 缓存/基线失效。"""
    import lumirss.routers.api_sources as routes

    async def fake_fetch(http_client, url):
        return SAMPLE

    monkeypatch.setattr(routes, "fetch_json", fake_fetch)
    created = client.post(
        "/api/v1/api-sources",
        json={
            "name": "发布接口",
            "endpoint": "https://api.example.com/releases",
            "itemsExpr": "data.list[*]",
            "fieldMap": {"id": "uid", "title": "heading"},
            "subscribe": False,
        },
    )
    assert created.status_code == 201, created.text
    uuid = created.json()["uuid"]
    # 先落一个 etag（模拟已抓取）
    atom = client.get(created.json()["atomPath"])
    assert atom.status_code == 200

    saved = client.post(
        f"/api/v1/api-sources/{uuid}/mapping-samples",
        json={"label": "用户样本", "sampleJson": SAMPLE},
    )
    assert saved.status_code == 201, saved.text
    sample_id = saved.json()["id"]

    preview = client.post(
        f"/api/v1/api-sources/{uuid}/mapping-samples/{sample_id}/preview",
        json={"fieldMap": TRIAL_MAP},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["totalAvailable"] == 2

    bound = client.post(
        f"/api/v1/api-sources/{uuid}/mapping-bind",
        json={"fieldMap": TRIAL_MAP},
    )
    assert bound.status_code == 200, bound.text

    listing = client.get("/api/v1/api-sources").json()["items"]
    source = next(s for s in listing if s["uuid"] == uuid)
    assert source["fieldMap"] == TRIAL_MAP
    assert source["lastStatus"] is None  # 绑定使既有缓存状态失效
    # last_success_at 是「生成见证」，按既有语义只前进不回退（FIX-246）
    # 绑定后的来源重新发布走新映射
    atom_after = client.get(created.json()["atomPath"])
    assert atom_after.status_code == 200
    assert "v1.0" in atom_after.text

    assert (
        client.delete(f"/api/v1/api-sources/{uuid}/mapping-samples/{sample_id}").status_code
        == 204
    )
    assert client.get(f"/api/v1/api-sources/{uuid}/mapping-samples").json()["items"] == []


def test_new301_cross_user_isolated(ab_env):  # noqa: F811 — pytest 夹具注册
    """A 的样本/来源对 B 完全不可见（B 访问得到一致的 404/空清单）。"""
    env = ab_env
    client = env["client"]
    a, b = env["a"], env["b"]
    created = client.post(
        "/api/v1/api-sources",
        headers=a,
        json={
            "name": "A 的来源",
            "endpoint": "https://api.example.com/items",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "title"},
            "subscribe": False,
        },
    )
    assert created.status_code == 201, created.text
    uuid = created.json()["uuid"]
    saved = client.post(
        f"/api/v1/api-sources/{uuid}/mapping-samples",
        headers=a,
        json={"label": "A 的样本", "sampleJson": {"id": 1, "title": "t"}},
    )
    assert saved.status_code == 201, saved.text

    # B 的来源清单不含 A 的来源；直接访问 A 的样本 → 404
    b_sources = client.get("/api/v1/api-sources", headers=b).json()["items"]
    assert all(s["uuid"] != uuid for s in b_sources)
    assert (
        client.get(f"/api/v1/api-sources/{uuid}/mapping-samples", headers=b).status_code
        == 404
    )
    # A 自己可见
    mine = client.get(f"/api/v1/api-sources/{uuid}/mapping-samples", headers=a).json()
    assert len(mine["items"]) == 1
    assert mine["items"][0]["label"] == "A 的样本"
