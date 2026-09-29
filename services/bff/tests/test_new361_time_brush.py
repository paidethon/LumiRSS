"""NEW-361 时间范围刷选 — 分布只由实际命中生成 / 窗口校验 / A/B 隔离。"""

from datetime import UTC, datetime, timedelta

from new2xx_ab import ab_env, seed_entry  # noqa: F401 — pytest 夹具注册

BRUSH_PATH = "/api/v1/search/time-brush"


def _day(offset_days: int) -> str:
    return (datetime.now(tz=UTC) - timedelta(days=offset_days)).strftime(
        "%Y-%m-%d"
    )


def _test_dates() -> list[int]:
    """三个固定相对偏移：3 / 10 / 100 天前（跨 92 天粒度边界）。"""
    return [3, 10, 100]


def test_new361_brush_buckets_from_actual_hits(ab_env):  # noqa: F811
    """分布只由实际命中生成：命中日有计数、空日补 0 但不伪造命中。"""
    client = ab_env["client"]
    for offset in _test_dates():
        seed_entry(
            ab_env,
            "a",
            f"n361-item-{offset}",
            title=f"刷选词 目标{offset}",
            published_at=(
                datetime.now(tz=UTC) - timedelta(days=offset)
            ).strftime("%Y-%m-%dT00:00:00Z"),
        )
    # 30 天日粒度窗口：只含 3/10 天前两篇。
    recent = client.get(
        f"{BRUSH_PATH}?q=刷选词&from={_day(29)}&to={_day(0)}",
        headers=ab_env["a"],
    )
    assert recent.status_code == 200, recent.text
    payload = recent.json()
    assert payload["granularity"] == "day"
    assert payload["total"] == 2
    counts = {b["key"]: b["count"] for b in payload["buckets"]}
    assert counts[_day(3)] == 1
    assert counts[_day(10)] == 1
    assert counts[_day(29)] == 0  # 空日补 0（渲染用，非伪造命中）
    assert len(payload["buckets"]) == 30

    # 长窗口切月粒度：三篇都进窗口。
    long_window = client.get(
        f"{BRUSH_PATH}?q=刷选词&from={_day(200)}&to={_day(0)}",
        headers=ab_env["a"],
    ).json()
    assert long_window["granularity"] == "month"
    assert long_window["total"] == 3
    assert sum(b["count"] for b in long_window["buckets"]) == 3
    assert "from/to" in long_window["hint"]


def test_new361_brush_validation(ab_env):  # noqa: F811
    client = ab_env["client"]
    assert client.get(f"{BRUSH_PATH}?q=刷选词", headers=ab_env["a"]).status_code == 422
    assert client.get(
        f"{BRUSH_PATH}?q=&from={_day(7)}&to={_day(0)}", headers=ab_env["a"]
    ).status_code == 400
    bad_format = client.get(
        f"{BRUSH_PATH}?q=刷选词&from=2026/01/01&to={_day(0)}", headers=ab_env["a"]
    )
    assert bad_format.status_code == 400
    inverted = client.get(
        f"{BRUSH_PATH}?q=刷选词&from={_day(0)}&to={_day(7)}", headers=ab_env["a"]
    )
    assert inverted.status_code == 400
    over_window = client.get(
        f"{BRUSH_PATH}?q=刷选词&from={_day(400)}&to={_day(0)}", headers=ab_env["a"]
    )
    assert over_window.status_code == 400


def test_new361_brush_isolation(ab_env):  # noqa: F811
    """分布是本人命中：A 的窗口计数对 B 全为 0。"""
    client = ab_env["client"]
    seed_entry(
        ab_env,
        "a",
        "n361-only-a",
        title="隔离词 唯A",
        published_at=(
            datetime.now(tz=UTC) - timedelta(days=2)
        ).strftime("%Y-%m-%dT00:00:00Z"),
    )
    a_view = client.get(
        f"{BRUSH_PATH}?q=隔离词&from={_day(29)}&to={_day(0)}",
        headers=ab_env["a"],
    ).json()
    assert a_view["total"] == 1
    b_view = client.get(
        f"{BRUSH_PATH}?q=隔离词&from={_day(29)}&to={_day(0)}",
        headers=ab_env["b"],
    ).json()
    assert b_view["total"] == 0
    assert all(bucket["count"] == 0 for bucket in b_view["buckets"])
