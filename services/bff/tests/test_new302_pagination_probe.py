"""NEW-302 API 分页试抓台 — 受限试抓/重复页/缺页诊断 + A/B 隔离。"""

import asyncio

import pytest

from lumirss.api_sources import ApiSourceFetchFailed
from lumirss.new302_pagination_probe import (
    PaginationProbeStore,
    clean_probe_max_pages,
    run_probe,
    url_shape,
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


def _fake_fetch_factory(pages: dict[str, object], failing: set[str] | None = None):
    failing = failing or set()

    async def fake_fetch(client, url):
        if url in failing:
            raise ApiSourceFetchFailed("API 端点返回 HTTP 500。")
        return pages[url]

    return fake_fetch


def test_new302_url_shape_hides_query_values():
    shape = url_shape("https://api.example.com/list?token=SECRET123&page=2")
    assert "SECRET123" not in shape
    assert "page" in shape and "token" in shape
    assert shape.startswith("https://api.example.com/list?")


def test_new302_probe_bounds():
    assert clean_probe_max_pages(None) == 5
    assert clean_probe_max_pages(3) == 3
    for bad in (0, 6, True, "2"):
        with pytest.raises(Exception):
            clean_probe_max_pages(bad)


def test_new302_probe_detects_duplicates_and_stops_at_empty(source_db):
    pages = {
        "https://api.example.com/list?page=1": {"items": [{"id": i} for i in range(3)]},
        "https://api.example.com/list?page=2": {"items": [{"id": i} for i in range(3)]},  # 重复载荷
        "https://api.example.com/list?page=3": {"items": []},
    }
    result = _run(
        run_probe(
            None,
            "https://api.example.com/list",
            '{"mode":"page","page_param":"page","max_pages":50}',
            "items[*]",
            max_pages=5,
            fetch=_fake_fetch_factory(pages),
        )
    )
    assert result["stopReason"] == "empty_page"
    assert result["duplicatePages"] == 1
    assert result["gapPages"] == 0
    assert result["pageCount"] == 3
    assert all("page=" not in p["url"] for p in result["pages"])  # 值不外泄


def test_new302_probe_records_gap_and_continues(source_db):
    """单页失败不中止试抓（生产是原子中止）——该页记为缺失（gap）。"""
    pages = {
        "https://api.example.com/list?page=1": {"items": [{"id": 1}]},
        "https://api.example.com/list?page=3": {"items": [{"id": 3}]},
    }
    result = _run(
        run_probe(
            None,
            "https://api.example.com/list",
            '{"mode":"page","page_param":"page"}',
            "items[*]",
            max_pages=3,
            fetch=_fake_fetch_factory(pages, failing={"https://api.example.com/list?page=2"}),
        )
    )
    assert result["gapPages"] == 1
    assert result["pageCount"] == 3
    missing = result["pages"][1]
    assert "error" in missing and missing["page"] == 2


def test_new302_probe_cursor_contract(source_db):
    pages = {
        "https://api.example.com/feed": {"items": [{"id": 1}], "next": "c1"},
        "https://api.example.com/feed?cursor=c1": {"items": [{"id": 2}], "next": "c1"},  # 游标重复
    }
    result = _run(
        run_probe(
            None,
            "https://api.example.com/feed",
            '{"mode":"cursor","cursor_path":"next"}',
            "items[*]",
            max_pages=5,
            fetch=_fake_fetch_factory(pages),
        )
    )
    assert result["stopReason"] == "cursor_repeat"
    assert result["itemCount"] == 2  # 检出重复游标即停（重复的第 3 页不抓）


def test_new302_probe_route_roundtrip(client, monkeypatch):
    import lumirss.new302_pagination_probe as probe_module

    pages = {
        "https://api.example.com/list?page=1": {"items": [{"id": 1}]},
        "https://api.example.com/list?page=2": {"items": [{"id": 1}]},
    }

    async def fake_fetch(client, url):
        return pages[url]

    monkeypatch.setattr(probe_module, "fetch_json", fake_fetch)
    created = client.post(
        "/api/v1/api-sources",
        json={
            "name": "分页源",
            "endpoint": "https://api.example.com/list",
            "itemsExpr": "items[*]",
            "fieldMap": {"id": "id", "title": "id"},
            "pagination": {"mode": "page", "page_param": "page"},
            "subscribe": False,
        },
    )
    assert created.status_code == 201, created.text
    uuid = created.json()["uuid"]

    probe = client.post(
        f"/api/v1/api-sources/{uuid}/pagination-probe", json={"maxPages": 2}
    )
    assert probe.status_code == 200, probe.text
    assert probe.json()["duplicatePages"] == 1

    # 快照持久化：GET 拿到同一结果（不再出网；GET 视图带 sourceUuid）
    again = client.get(f"/api/v1/api-sources/{uuid}/pagination-probe")
    assert again.status_code == 200
    stored = again.json()
    assert stored["stopReason"] == probe.json()["stopReason"]
    assert stored["pageCount"] == probe.json()["pageCount"]
    assert stored["duplicatePages"] == probe.json()["duplicatePages"]

    # 来源上不存在试抓 → 诚实 404
    created2 = client.post(
        "/api/v1/api-sources",
        json={
            "name": "未试抓",
            "endpoint": "https://api.example.com/other",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "t"},
            "subscribe": False,
        },
    )
    assert (
        client.get(
            f"/api/v1/api-sources/{created2.json()['uuid']}/pagination-probe"
        ).status_code
        == 404
    )


def test_new302_probe_persist_roundtrip(source_db):
    store = PaginationProbeStore(source_db)
    result = {
        "probedAt": "2026-09-29T00:00:00Z",
        "mode": "page",
        "stopReason": "empty_page",
        "pageCount": 2,
        "itemCount": 5,
        "duplicatePages": 1,
        "gapPages": 0,
        "pages": [{"page": 1, "url": "https://x/?p", "itemCount": 5}],
    }
    _run(store.save_result("src-1", result))
    stored = _run(store.last_result("src-1"))
    assert stored is not None
    assert stored["duplicatePages"] == 1
    assert stored["pages"][0]["itemCount"] == 5
    # 同来源二次试抓覆盖（只留最近一次）
    result["pageCount"] = 4
    _run(store.save_result("src-1", result))
    assert _run(store.last_result("src-1"))["pageCount"] == 4


def test_new302_cross_user_isolated(ab_env):  # noqa: F811 — pytest 夹具注册
    """B 看不到 A 的试抓快照；对 A 的来源发起试抓 → 404。"""
    env = ab_env
    client = env["client"]
    a, b = env["a"], env["b"]
    created = client.post(
        "/api/v1/api-sources",
        headers=a,
        json={
            "name": "A 的分页源",
            "endpoint": "https://api.example.com/list",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "t"},
            "subscribe": False,
        },
    )
    assert created.status_code == 201, created.text
    uuid = created.json()["uuid"]
    import lumirss.new302_pagination_probe as probe_module

    async def fake_fetch(client_arg, url):
        return {"items": [{"id": 1}]}

    # ab_env 不暴露 monkeypatch —— 直接改模块属性并在测试后还原。
    original = probe_module.fetch_json
    probe_module.fetch_json = fake_fetch
    try:
        probed = client.post(
            f"/api/v1/api-sources/{uuid}/pagination-probe", headers=a, json={}
        )
        assert probed.status_code == 200, probed.text
    finally:
        probe_module.fetch_json = original

    assert (
        client.get(f"/api/v1/api-sources/{uuid}/pagination-probe", headers=b).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/api-sources/{uuid}/pagination-probe", headers=b, json={}
        ).status_code
        == 404
    )
    mine = client.get(f"/api/v1/api-sources/{uuid}/pagination-probe", headers=a)
    assert mine.status_code == 200
