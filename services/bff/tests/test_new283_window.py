"""NEW-283 简报截稿窗口 — 显式时区 / 截止点 / 迟到调回（跨时区断言）。"""

from datetime import datetime, timedelta

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new281_helpers import iso, parse_iso, seed


def iso_base(base: datetime, offset_seconds: int) -> str:
    """窗口边界 ± 偏移 → 播种时刻（相对真实边界推导，不写死日历日期）。"""
    return (base + timedelta(seconds=offset_seconds)).isoformat(timespec="seconds")


def _put_window(client, headers, timezone, cutoff, days):
    return client.put(
        "/api/v1/briefings/window",
        json={"timezone": timezone, "cutoffTime": cutoff, "periodDays": days},
        headers=headers,
    )


def _get_window(client, headers):
    return client.get("/api/v1/briefings/window", headers=headers).json()


def test_window_put_get_bounds(ab_env):  # noqa: F811
    """上海 18:00 截稿 = UTC 10:00；窗口 = [cutoff-24h, cutoff)；下一期起点 = cutoff。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    put = _put_window(client, a, "Asia/Shanghai", "18:00", 1)
    assert put.status_code == 200, put.text
    window = put.json()
    assert window["timezone"] == "Asia/Shanghai"
    assert window["cutoffTime"] == "18:00"
    assert window["cutoffUtc"].endswith("10:00:00+00:00")
    start = parse_iso(window["startUtc"])
    cutoff = parse_iso(window["cutoffUtc"])
    assert (cutoff - start) == timedelta(days=1)
    assert window["nextWindowStartUtc"] == window["cutoffUtc"]

    fetched = _get_window(client, a)
    assert fetched["configured"] is True
    assert fetched["cutoffUtc"]


def test_cross_timezone_bounds_differ(ab_env):  # noqa: F811
    """同一墙钟截点在不同时区 → UTC 边界差 ≥ 7 小时（显式时区化的意义）。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    utc_window = _put_window(client, a, "UTC", "18:00", 1).json()
    shanghai_window = _put_window(client, a, "Asia/Shanghai", "18:00", 1).json()
    delta = abs(
        (parse_iso(utc_window["cutoffUtc"]) - parse_iso(shanghai_window["cutoffUtc"])).total_seconds()
    )
    assert delta >= 7 * 3600
    # 两个时区的窗口长度都是整周期
    for window in (utc_window, shanghai_window):
        length = parse_iso(window["cutoffUtc"]) - parse_iso(window["startUtc"])
        assert length == timedelta(days=1)


def test_late_entry_requires_explicit_pullback(ab_env):  # noqa: F811
    """截稿点之后的文章属下一期；不带 pullBack 拒收，带 pullBack 调回并标记。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    assert _put_window(client, a, "Asia/Shanghai", "18:00", 1).status_code == 200
    bounds = _get_window(client, a)
    cutoff = bounds["cutoffUtc"]

    late_card = seed(env, "a", title="截稿后的文章", published=iso_base(parse_iso(cutoff), 60))
    in_card = seed(env, "a", title="窗口内的文章", published=iso_base(parse_iso(cutoff), -7200))

    rejected = client.post(
        "/api/v1/briefings",
        json={
            "title": "迟到未调回",
            "sections": [{"key": "main", "label": "正文"}],
            "items": [
                {"entryRef": late_card["entryRef"], "sectionKey": "main", "title": late_card["title"],
                 "publishedAt": late_card.get("publishedAt", "")},
                {"entryRef": in_card["entryRef"], "sectionKey": "main", "title": in_card["title"],
                 "publishedAt": in_card.get("publishedAt", "")},
            ],
        },
        headers=a,
    )
    assert rejected.status_code == 422, rejected.text
    error = rejected.json()["error"]
    assert error["type"] == "briefing_late_entry"
    assert late_card["entryRef"] in error["entryRefs"]

    pulled = client.post(
        "/api/v1/briefings",
        json={
            "title": "迟到已调回",
            "sections": [{"key": "main", "label": "正文"}],
            "items": [
                {"entryRef": late_card["entryRef"], "sectionKey": "main", "title": late_card["title"],
                 "publishedAt": late_card.get("publishedAt", ""), "pullBack": True},
                {"entryRef": in_card["entryRef"], "sectionKey": "main", "title": in_card["title"],
                 "publishedAt": in_card.get("publishedAt", "")},
            ],
        },
        headers=a,
    )
    assert pulled.status_code == 201, pulled.text
    items = {i["entryRef"]: i for i in pulled.json()["items"]}
    assert items[late_card["entryRef"]]["pulledBack"] is True
    assert items[in_card["entryRef"]]["pulledBack"] is False


def test_window_validation(ab_env):  # noqa: F811
    """非法时区 / 截点 / 周期 → 422；DELETE 后 configured=false，再删 404。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    assert _put_window(client, a, "Mars/Olympus", "18:00", 1).status_code == 422
    assert _put_window(client, a, "Asia/Shanghai", "24:00", 1).status_code == 422
    assert _put_window(client, a, "Asia/Shanghai", "1800", 1).status_code == 422
    assert _put_window(client, a, "Asia/Shanghai", "18:00", 3).status_code == 422
    assert _put_window(client, a, "Asia/Shanghai", "18:00", 7).status_code == 200

    assert client.delete("/api/v1/briefings/window", headers=a).status_code == 204
    assert _get_window(client, a)["configured"] is False
    assert client.delete("/api/v1/briefings/window", headers=a).status_code == 404


def test_without_window_compose_is_free(ab_env):  # noqa: F811
    """未配置窗口 → 无迟到拦截（自由编排不受周期约束）。"""
    env = ab_env
    client = env["client"]
    b = env["b"]
    assert _get_window(client, b)["configured"] is False
    card = seed(env, "b", title="任意时刻", published=iso(hours=-1))
    created = client.post(
        "/api/v1/briefings",
        json={
            "title": "自由简报",
            "sections": [{"key": "main", "label": "正文"}],
            "items": [
                {"entryRef": card["entryRef"], "sectionKey": "main", "title": card["title"],
                 "publishedAt": iso(hours=-1)}
            ],
        },
        headers=b,
    )
    assert created.status_code == 201, created.text


def test_cross_user_window_isolated(ab_env):  # noqa: F811
    """A 的窗口对 B 不可见（per-user 单行配置）。"""
    env = ab_env
    client = env["client"]
    assert _put_window(client, env["a"], "Europe/Berlin", "20:00", 7).status_code == 200
    b_window = _get_window(client, env["b"])
    assert b_window["configured"] is False
    a_window = _get_window(client, env["a"])
    assert a_window["timezone"] == "Europe/Berlin"
    assert a_window["periodDays"] == 7
