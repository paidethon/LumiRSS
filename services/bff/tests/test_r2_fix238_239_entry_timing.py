"""FIX-238/FIX-239 — 转换 Atom 的条目时间契约（API Sources → FreshRSS）。

FIX-238（日期缺失）：旧实现把无发布日期条目的 ``<updated>`` 写成 feed 级
``feed_updated``——该值随每次内容变化前进，FreshRSS 于是每轮刷新都把同一
篇无日期条目重新顶到时间线上（反复置顶）。契约：缺失日期的条目钉在来源
的稳定 created_at（首次注册时刻，永不移动），``<published>`` 缺席即缺失
标记。

FIX-239（未来日期）：远超容差（> now + 24h，与 N034 投影分类同一阈值）的
声明日期按“不可信排序时间”处理——绝不像声明的值那样照发（会把条目永久
停在未来、饿死正常时间线），也不再让 feed 级 updated 被一条未来条目推进
未来。规则在 _entry_timing / compute_feed_updated 的 docstring 中明示。
"""

import xml.etree.ElementTree as SafeET

from lumirss.api_sources import (
    ApiSourceRecord,
    compute_feed_updated,
    generate_atom,
    preview_atom_entries,
)

_NS = "{http://www.w3.org/2005/Atom}"


def _record(created_at: str = "2026-09-01T08:00:00Z") -> ApiSourceRecord:
    return ApiSourceRecord(
        uuid="test-uuid",
        name="示例源",
        endpoint="https://api.example.com/items",
        items_expr="[*]",
        field_map='{"id":"id","title":"title"}',
        enabled=True,
        secret="s",
        etag=None,
        last_status=None,
        last_success_at=None,
        last_error=None,
        created_at=created_at,
    )


def _entries(atom_xml: str) -> dict[str, dict]:
    root = SafeET.fromstring(atom_xml)
    out: dict[str, dict] = {}
    for entry in root.findall(f"{_NS}entry"):
        published = entry.find(f"{_NS}published")
        updated = entry.find(f"{_NS}updated")
        out[entry.find(f"{_NS}title").text] = {
            "published": published.text if published is not None else None,
            "updated": updated.text if updated is not None else None,
        }
    return out


def test_dateless_entry_updated_is_pinned_not_feed_updated():
    """FIX-238：无日期条目的 <updated> 钉在来源 created_at，绝不取会随
    内容前进的 feed_updated；<published> 缺席（缺失标记）。"""
    record = _record(created_at="2026-09-01T08:00:00Z")
    items = [{"id": "1", "title": "无日期文章"}]
    feed_updated = "2026-09-20T00:00:00+00:00"  # 已被别的内容推进的 feed 时钟
    atom = generate_atom(record, items, feed_updated, "http://bff:8000")
    entry = _entries(atom)["无日期文章"]
    assert entry["published"] is None  # 缺失标记：<published> 不伪造
    assert entry["updated"] == "2026-09-01T08:00:00+00:00"  # 钉在 created_at


def test_dateless_entry_does_not_move_when_feed_clock_advances():
    """FIX-238 端到端：新文章到达推进 feed updated 后，同一篇无日期条目
    的 <updated> 保持原值（不再被每轮刷新反复置顶）。"""
    record = _record(created_at="2026-09-01T08:00:00Z")
    before = generate_atom(
        record,
        [{"id": "1", "title": "无日期文章"}],
        "2026-09-02T00:00:00+00:00",
        "http://bff:8000",
    )
    after = generate_atom(
        record,
        [
            {"id": "1", "title": "无日期文章"},
            {"id": "2", "title": "新文章", "published": "2026-09-21T00:00:00Z"},
        ],
        "2026-09-21T00:00:00+00:00",
        "http://bff:8000",
    )
    assert (
        _entries(before)["无日期文章"]["updated"]
        == _entries(after)["无日期文章"]["updated"]
    )


def test_far_future_entry_is_capped_not_forwarded():
    """FIX-239：远未来声明日期不进 <published>（声明值不得把条目永久停
    在未来），条目排序时间钉在稳定 created_at。"""
    record = _record(created_at="2026-09-01T08:00:00Z")
    items = [{"id": "1", "title": "未来文章", "published": "2030-01-01T00:00:00Z"}]
    atom = generate_atom(
        record, items, "2026-09-01T08:00:00+00:00", "http://bff:8000"
    )
    entry = _entries(atom)["未来文章"]
    assert entry["published"] is None  # 声明值不转发（排序封顶）
    assert entry["updated"] == "2026-09-01T08:00:00+00:00"  # 稳定钉扎


def test_near_future_entry_within_tolerance_keeps_declared_date():
    """容差窗口内（≤ now + 24h）的声明日期原样保留——只封顶“远”未来。"""
    record = _record(created_at="2026-09-01T08:00:00Z")
    items = [
        {
            "id": "1",
            "title": "稍后发布",
            "published": "2026-09-02T02:00:00Z",  # created_at + 18h < 24h
        }
    ]
    from datetime import datetime

    now_epoch = datetime.fromisoformat("2026-09-01T08:00:00+00:00").timestamp()
    atom = generate_atom(
        record,
        items,
        "2026-09-01T08:00:00+00:00",
        "http://bff:8000",
        now_epoch=now_epoch,
    )
    entry = _entries(atom)["稍后发布"]
    assert entry["published"] == "2026-09-02T02:00:00+00:00"
    assert entry["updated"] == "2026-09-02T02:00:00+00:00"


def test_feed_updated_ignores_far_future_candidates():
    """FIX-239 feed 级：一条未来条目不得把 feed updated 推进未来
    （feed 时钟被推到未来同样制造时间线断层与 304 漂移）。"""
    items = [
        {"id": "1", "title": "正常", "published": "2026-09-10T00:00:00Z"},
        {"id": "2", "title": "未来", "published": "2030-01-01T00:00:00Z"},
    ]
    updated = compute_feed_updated(items, None, "2026-09-01T08:00:00Z")
    assert updated == "2026-09-10T00:00:00+00:00"


def test_preview_mirrors_ingestion_timestamp_rule():
    """F041 契约：预览与实际摄取同一时间规则——无日期/远未来的条目在
    预览里同样无 <published>、updated 取稳定回退（而非 feed 时钟）。"""
    items = [
        {"id": "1", "title": "无日期"},
        {"id": "2", "title": "未来", "published": "2030-01-01T00:00:00Z"},
        {"id": "3", "title": "正常", "published": "2026-09-10T00:00:00Z"},
    ]
    preview = preview_atom_entries(
        items, stable_fallback="2026-09-01T08:00:00Z"
    )
    by_title = {entry["title"]: entry for entry in preview}
    assert by_title["无日期"]["published"] is None
    assert by_title["未来"]["published"] is None
    assert by_title["无日期"]["updated"] == "2026-09-01T08:00:00+00:00"
    assert by_title["未来"]["updated"] == "2026-09-01T08:00:00+00:00"
    assert by_title["正常"]["published"] == "2026-09-10T00:00:00+00:00"


def test_route_dateless_entry_stays_pinned_across_refreshes(client, monkeypatch):
    """路由级端到端：两轮上游拉取之间 feed 时钟前进，无日期条目的
    <updated> 不动（FreshRSS 侧不会反复置顶）。"""
    import lumirss.routers.api_sources as routes

    data_v1 = [{"id": 1, "name": "无日期文章", "html_url": "https://e.com/1"}]
    data_v2 = [
        *data_v1,
        {
            "id": 2,
            "name": "新文章",
            "html_url": "https://e.com/2",
            "published_at": "2026-09-21T00:00:00Z",
        },
    ]

    async def fake_fetch(client_arg, endpoint: str):
        _ = client_arg
        return _current["data"]

    _current = {"data": data_v1}
    monkeypatch.setattr(routes, "fetch_json", fake_fetch)
    created = client.post(
        "/api/v1/api-sources",
        json={
            "name": "时间契约",
            "endpoint": "https://api.example.com/items",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "name", "url": "html_url", "published": "published_at"},
            "subscribe": False,
        },
    )
    assert created.status_code == 201
    atom_path = created.json()["atomPath"]

    first = SafeET.fromstring(client.get(atom_path).text)
    pinned_before = [
        entry.find(f"{_NS}updated").text
        for entry in first.findall(f"{_NS}entry")
        if entry.find(f"{_NS}title").text == "无日期文章"
    ][0]

    _current["data"] = data_v2
    second = SafeET.fromstring(client.get(atom_path).text)
    pinned_after = [
        entry.find(f"{_NS}updated").text
        for entry in second.findall(f"{_NS}entry")
        if entry.find(f"{_NS}title").text == "无日期文章"
    ][0]
    assert pinned_before == pinned_after
