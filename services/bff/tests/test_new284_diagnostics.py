"""NEW-284 简报缺刊诊断 — 缺失输入 + 执行阶段如实诊断，可补后重跑。"""

from datetime import timedelta

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new281_helpers import iso, parse_iso, seed


def iso_base(base, offset_seconds):
    """窗口边界 ± 偏移 → 播种时刻（相对真实边界，不写死日历日期）。"""
    return (base + timedelta(seconds=offset_seconds)).isoformat(timespec="seconds")


def _put_window(client, headers):
    return client.put(
        "/api/v1/briefings/window",
        json={"timezone": "Asia/Shanghai", "cutoffTime": "18:00", "periodDays": 1},
        headers=headers,
    )


def _generate(client, headers, **payload):
    return client.post("/api/v1/briefings/generate", json=payload, headers=headers)


def test_generate_without_window_diagnosed(ab_env):  # noqa: F811
    """无窗口无范围 → 422 stage=candidates，missing 指名 window；attempt 留痕。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    failed = _generate(client, a)
    assert failed.status_code == 422, failed.text
    error = failed.json()["error"]
    assert error["type"] == "briefing_inputs_missing"
    assert error["stage"] == "candidates"
    assert any(m["field"] == "window" for m in error["missing"])
    assert error["attemptId"]

    attempts = client.get("/api/v1/briefings/attempts", headers=a).json()
    assert attempts["count"] >= 1
    latest = attempts["attempts"][0]
    assert latest["status"] == "failed"
    assert latest["stage"] == "candidates"
    assert any(m["field"] == "window" for m in latest["missing"])


def test_generate_window_success_and_late_excluded(ab_env):  # noqa: F811
    """窗口生成成功：草稿 + rule 编辑来源；截稿后的条目不进本期并如实报数。

    播种相对真实窗口边界（cutoff±偏移），与运行墙钟无关——上海 18:00
    截稿 = UTC 10:00，相对 now 播种会在 10:00-15:00 UTC 间漂出窗口。
    """
    env = ab_env
    client = env["client"]
    a = env["a"]
    assert _put_window(client, a).status_code == 200
    bounds = client.get("/api/v1/briefings/window", headers=a).json()
    cutoff = parse_iso(bounds["cutoffUtc"])

    inside1 = seed(env, "a", title="窗口内一", published=iso_base(cutoff, -7200))
    inside2 = seed(env, "a", title="窗口内二", published=iso_base(cutoff, -28800))
    late = seed(env, "a", title="截稿后来文", published=iso_base(cutoff, 60))

    result = _generate(client, a)
    assert result.status_code == 201, result.text
    body = result.json()
    issue = body["issue"]
    assert issue["status"] == "draft"
    assert issue["source"] == "generate"
    refs = {i["entryRef"] for i in issue["items"]}
    assert {inside1["entryRef"], inside2["entryRef"]} <= refs
    assert late["entryRef"] not in refs
    assert all(i["provenance"] == "rule" for i in issue["items"])
    assert all(i["provenanceLabel"] == "规则推荐" for i in issue["items"])

    # excludedLate 如实 = 已截稿区间 [cutoff, now) 内的已播文章数
    # （cutoff+60s 可能尚在未来——那它就是 0，断言照样精确）
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat(timespec="seconds")
    expected_late = sum(
        1
        for p in (inside1["publishedAt"], inside2["publishedAt"], late["publishedAt"])
        if bounds["cutoffUtc"] <= p < now
    )
    assert body["excludedLate"] == expected_late

    attempts = client.get("/api/v1/briefings/attempts", headers=a).json()
    assert attempts["attempts"][0]["status"] == "ok"


def test_generate_section_rule_missing_then_fixed(ab_env):  # noqa: F811
    """starred 规则筛不出 → 422 stage=sections 点名栏目；标星后重跑成功。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    assert _put_window(client, a).status_code == 200
    bounds = client.get("/api/v1/briefings/window", headers=a).json()
    cutoff = parse_iso(bounds["cutoffUtc"])
    seed(env, "a", title="未标星", published=iso_base(cutoff, -7200))

    sections = [
        {"key": "picks", "label": "精选", "rule": "starred", "budget": 400},
        {"key": "news", "label": "快讯", "rule": "recent", "budget": 400},
    ]
    failed = _generate(client, a, sections=sections)
    assert failed.status_code == 422, failed.text
    error = failed.json()["error"]
    assert error["type"] == "briefing_inputs_missing"
    assert error["stage"] == "sections"
    assert any(m["field"] == "section:picks" for m in error["missing"])
    assert not any(m["field"] == "section:news" for m in error["missing"])

    # 补输入：把一篇文章标星 → 重跑成功（同窗口同配方）
    seed(env, "a", title="已标星", published=iso_base(cutoff, -3600), starred=1)
    retry = _generate(client, a, sections=sections)
    assert retry.status_code == 201, retry.text
    issue = retry.json()["issue"]
    picks = [i for i in issue["items"] if i["sectionKey"] == "picks"]
    assert picks and picks[0]["title"] == "已标星"

    # 台账留下 failed → ok 完整轨迹
    attempts = client.get("/api/v1/briefings/attempts", headers=a).json()
    statuses = [a["status"] for a in attempts["attempts"]][:2]
    assert "failed" in statuses and "ok" in statuses


def test_generate_explicit_range_without_window(ab_env):  # noqa: F811
    """显式范围可替代窗口（from/to 合法即生成）。"""
    env = ab_env
    client = env["client"]
    b = env["b"]
    card = seed(env, "b", title="B 的范围文章", published=iso(hours=-3))
    result = _generate(
        client,
        b,
        rangeFrom=iso(days=-2),
        rangeTo=iso(hours=-1),
        sections=[{"key": "main", "label": "正文", "rule": "recent", "budget": 400}],
    )
    assert result.status_code == 201, result.text
    refs = {i["entryRef"] for i in result.json()["issue"]["items"]}
    assert card["entryRef"] in refs


def test_generate_empty_window_diagnosed(ab_env):  # noqa: F811
    """窗口内 0 篇 → 422 缺刊诊断（绝不给空白成功页）。"""
    env = ab_env
    client = env["client"]
    b = env["b"]
    assert _put_window(client, b).status_code == 200
    failed = _generate(client, b)
    assert failed.status_code == 422
    error = failed.json()["error"]
    assert error["stage"] == "candidates"
    assert any(m["field"] == "entries" for m in error["missing"])


def test_cross_user_attempts_isolated(ab_env):  # noqa: F811
    """A 的生成尝试对 B 不可见。"""
    env = ab_env
    client = env["client"]
    assert _generate(client, env["a"]).status_code == 422
    b_attempts = client.get("/api/v1/briefings/attempts", headers=env["b"]).json()
    assert b_attempts["count"] == 0
