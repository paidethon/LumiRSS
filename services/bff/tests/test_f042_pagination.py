"""F042 API 分页采样 — page/cursor 走页、停止条件、原子性、SSRF 校验。

Hermetic：上游 fetch 统一 monkeypatch lumirss.api_sources.fetch_json。
"""

import asyncio
import json

import pytest

from lumirss.api_sources import (
    ApiSourceFetchFailed,
    PaginationInvalid,
    fetch_json_pages,
    validate_pagination,
)

FIELD_MAP = {"id": "id", "title": "title"}


def _run(coroutine):
    return asyncio.run(coroutine)


def _page(n: int, size: int = 2) -> list[dict]:
    return [{"id": f"p{n}-{i}", "title": f"第 {n} 页第 {i} 条"} for i in range(size)]


class FakeUpstream:
    """3 页 fixture：page 模式按 ?page=N 分发；cursor 模式按 ?cursor= 分发。"""

    def __init__(
        self,
        pages: dict[str, object],
        fail_on: str | None = None,
        default: object | None = None,
    ):
        self.pages = pages
        self.fail_on = fail_on  # URL 子串 → 抛 429
        self.default = default  # 无 key 命中时的响应
        self.calls: list[str] = []

    async def __call__(self, client_arg, endpoint: str) -> object:
        _ = client_arg
        self.calls.append(endpoint)
        if self.fail_on and self.fail_on in endpoint:
            raise ApiSourceFetchFailed("API 端点返回 HTTP 429。")
        for key, payload in self.pages.items():
            if key in endpoint:
                return payload
        return self.default


def test_f042_validate_pagination_bounds():
    assert json.loads(validate_pagination(None))["mode"] == "none"
    page_cfg = json.loads(
        validate_pagination({"mode": "page", "page_param": "p", "max_pages": 3})
    )
    assert page_cfg["page_param"] == "p"
    assert page_cfg["max_pages"] == 3
    with pytest.raises(PaginationInvalid):
        validate_pagination({"mode": "page"})  # 缺 page_param
    with pytest.raises(PaginationInvalid):
        validate_pagination({"mode": "cursor"})  # 缺 cursor_path
    with pytest.raises(PaginationInvalid):
        validate_pagination({"mode": "cursor", "cursor_path": "this ][ bad"})
    with pytest.raises(PaginationInvalid):
        validate_pagination({"mode": "page", "page_param": "p", "max_pages": 51})
    with pytest.raises(PaginationInvalid):
        validate_pagination({"mode": "page", "page_param": "p", "max_items": 1001})
    cursor_cfg = validate_pagination(
        {"mode": "cursor", "cursor_path": "meta.next", "max_pages": 3, "max_items": 10}
    )
    assert json.loads(cursor_cfg)["cursor_path"] == "meta.next"


def test_f042_page_walk_three_pages_and_empty_page_stop():
    """本地 fixture 3 页：第 4 页空 → empty_page 停止，逐页拼接。"""
    upstream = FakeUpstream(
        {"page=1": _page(1), "page=2": _page(2), "page=3": _page(3), "page=4": []}
    )
    import lumirss.api_sources as mod

    original = mod.fetch_json
    mod.fetch_json = upstream  # type: ignore[method-assign]
    try:
        payloads, stop = _run(
            fetch_json_pages(
                None,
                "https://api.example.com/items",
                validate_pagination({"mode": "page", "page_param": "page"}),
                "[*]",
            )
        )
    finally:
        mod.fetch_json = original  # type: ignore[method-assign]
    assert stop == "empty_page"
    assert len(payloads) == 3
    assert upstream.calls == [
        "https://api.example.com/items?page=1",
        "https://api.example.com/items?page=2",
        "https://api.example.com/items?page=3",
        "https://api.example.com/items?page=4",
    ]
    mapped = [item for payload in payloads for item in payload]
    assert len(mapped) == 6


def test_f042_cursor_mode_walks_and_stops_on_missing_cursor():
    upstream = FakeUpstream(
        {"cursor=tok-2": {"items": _page(2), "meta": {"next": None}}},
        default={"items": _page(1), "meta": {"next": "tok-2"}},
    )
    import lumirss.api_sources as mod

    original = mod.fetch_json
    mod.fetch_json = upstream  # type: ignore[method-assign]
    try:
        payloads, stop = _run(
            fetch_json_pages(
                None,
                "https://api.example.com/feed",
                validate_pagination({"mode": "cursor", "cursor_path": "meta.next"}),
                "items[*]",
            )
        )
    finally:
        mod.fetch_json = original  # type: ignore[method-assign]
    assert stop == "cursor_missing"
    assert len(payloads) == 2
    assert "cursor=tok-2" in upstream.calls[1]


def test_f042_cursor_repeat_stops_without_loop():
    """重复游标 → cursor_repeat 停止（不无限循环）。"""
    upstream = FakeUpstream(
        {"cursor=same": {"items": _page(2), "next": "same"}},
        default={"items": _page(1), "next": "same"},
    )
    import lumirss.api_sources as mod

    original = mod.fetch_json
    mod.fetch_json = upstream  # type: ignore[method-assign]
    try:
        payloads, stop = _run(
            fetch_json_pages(
                None,
                "https://api.example.com/feed",
                validate_pagination(
                    {"mode": "cursor", "cursor_path": "next", "max_pages": 10}
                ),
                "items[*]",
            )
        )
    finally:
        mod.fetch_json = original  # type: ignore[method-assign]
    assert stop == "cursor_repeat"
    assert len(payloads) == 2  # 第二页发现重复即停


def test_f042_max_pages_and_max_items_stop():
    upstream = FakeUpstream({key: _page(1, 1) for key in ("",)})
    import lumirss.api_sources as mod

    original = mod.fetch_json
    mod.fetch_json = upstream  # type: ignore[method-assign]
    try:
        _payloads, stop_pages = _run(
            fetch_json_pages(
                None,
                "https://api.example.com/feed",
                validate_pagination(
                    {"mode": "page", "page_param": "page", "max_pages": 3, "max_items": 100}
                ),
                "[*]",
            )
        )
        _payloads2, stop_items = _run(
            fetch_json_pages(
                None,
                "https://api.example.com/feed",
                validate_pagination(
                    {"mode": "page", "page_param": "page", "max_pages": 50, "max_items": 4}
                ),
                "[*]",
            )
        )
    finally:
        mod.fetch_json = original  # type: ignore[method-assign]
    assert stop_pages == "max_pages"
    assert stop_items == "max_items"


def test_f042_mid_walk_429_aborts_atomically_no_publish(client, monkeypatch):
    """中途 429 → 整批不入库：feed 保持 last-known-good + 错误如实上报。"""
    import lumirss.api_sources as mod
    import lumirss.routers.api_sources as routes

    good = [{"id": "old-1", "title": "旧内容", "published_at": "2026-09-01T00:00:00Z"}]

    async def good_fetch(client_arg, endpoint):
        _ = client_arg, endpoint
        return good

    monkeypatch.setattr(mod, "fetch_json", good_fetch)
    monkeypatch.setattr(routes, "fetch_json", good_fetch)
    created = client.post(
        "/api/v1/api-sources",
        json={
            "name": "Paged",
            "endpoint": "https://api.example.com/items",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "title", "published": "published_at"},
            "subscribe": False,
        },
    )
    assert created.status_code == 201
    body = created.json()
    atom = client.get(body["atomPath"])
    assert atom.status_code == 200

    # 现在打开分页且第 2 页 429
    paged = FakeUpstream(
        {"page=1": _page(1), "page=2": _page(2), "page=3": []},
        fail_on="page=2",
    )

    async def paged_fetch(client_arg, endpoint):
        return await paged(client_arg, endpoint)

    monkeypatch.setattr(mod, "fetch_json", paged_fetch)
    monkeypatch.setattr(routes, "fetch_json", paged_fetch)
    client.patch(
        f"/api/v1/api-sources/{body['uuid']}",
        json={"pagination": {"mode": "page", "page_param": "page"}},
    )
    atom2 = client.get(body["atomPath"])
    assert atom2.status_code == 502  # 无 last-good（PATCH 清空）→ 诚实失败
    listing = client.get("/api/v1/api-sources").json()["items"]
    assert listing[0]["lastStatus"] == "fetch_failed"
    assert "429" in listing[0]["lastError"]
    assert "未发布" in listing[0]["lastError"]


def test_f042_cursor_target_url_passes_ssrf_check(client, monkeypatch):
    """cursor 拼接后的目标 URL 出站前过 SSRF 校验：内网地址拒绝。"""
    import lumirss.api_sources as mod
    from lumirss.clip_fetch import ClipForbidden

    checked: list[str] = []

    async def production_validate_hop(url: str) -> None:
        """模拟生产 validate_hop：记录每次校验；内网目标拒绝。"""
        checked.append(url)
        if "cursor=10.0.0.5" in url:
            raise ClipForbidden("页面地址解析到非公网地址，已拒绝。", "unsafe_address")

    async def stub_fetch(client_arg, endpoint):
        # 与生产 fetch_json 同一契约：出站前先过 validate_hop
        await mod.validate_hop(endpoint)
        return {"items": _page(1), "next": "10.0.0.5"}

    monkeypatch.setattr(mod, "validate_hop", production_validate_hop)
    monkeypatch.setattr(mod, "fetch_json", stub_fetch)
    with pytest.raises(ClipForbidden):
        _run(
            fetch_json_pages(
                None,
                "https://api.example.com/feed",
                validate_pagination({"mode": "cursor", "cursor_path": "next"}),
                "items[*]",
            )
        )
    # 首页与 cursor 目标 URL 都经过了 SSRF 校验，且游标页在校验处被拒
    assert checked[0] == "https://api.example.com/feed"
    assert checked[1] == "https://api.example.com/feed?cursor=10.0.0.5"


def test_f042_dry_run_pagination_returns_pages_and_stop_reason(client, monkeypatch):
    """preview dry_run_pagination：{pages, stopReason}，不入库。"""
    import lumirss.api_sources as mod
    import lumirss.routers.api_sources as routes

    upstream = FakeUpstream(
        {"page=1": _page(1), "page=2": _page(2), "page=3": []}
    )
    monkeypatch.setattr(mod, "fetch_json", upstream)
    monkeypatch.setattr(routes, "fetch_json", upstream)
    response = client.post(
        "/api/v1/api-sources/preview",
        json={
            "endpoint": "https://api.example.com/items",
            "itemsExpr": "[*]",
            "fieldMap": FIELD_MAP,
            "pagination": {"mode": "page", "page_param": "page"},
            "dryRunPagination": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["paginationDryRun"]["stopReason"] == "empty_page"
    assert [p["mappedItems"] for p in body["paginationDryRun"]["pages"]] == [2, 2]
    # 试跑零写入
    assert client.get("/api/v1/api-sources").json()["items"] == []
