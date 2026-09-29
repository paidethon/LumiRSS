"""NEW-370 搜索结果评注 — 有用/无关标记 / 默认排序不变 / 显式方案才重排 / 隔离。"""

from datetime import UTC, datetime, timedelta

from lumirss.entryref import encode_entry_ref
from new2xx_ab import ab_env, seed_entry  # noqa: F401 — pytest 夹具注册

FEEDBACK_PATH = "/api/v1/search/feedback"
SCHEME_PATH = "/api/v1/search/ranking-scheme"
RERANKED_PATH = "/api/v1/search/reranked"


def _seed_two_hits(env):
    """e1（较旧，将被标「有用」）与 e2（较新，默认排序在前）。"""
    seed_entry(
        env,
        "a",
        "n370-e1",
        title="评注 目标一",
        published_at=(datetime.now(tz=UTC) - timedelta(days=5)).strftime(
            "%Y-%m-%dT00:00:00Z"
        ),
    )
    seed_entry(
        env,
        "a",
        "n370-e2",
        title="评注 目标二",
        published_at=(datetime.now(tz=UTC) - timedelta(days=1)).strftime(
            "%Y-%m-%dT00:00:00Z"
        ),
    )
    return (
        encode_entry_ref('n370-e1'),
        encode_entry_ref('n370-e2'),
    )


def test_new370_feedback_record_and_default_order_untouched(ab_env):  # noqa: F811
    """评注可写可覆盖；默认搜索排序完全不因反馈改变。"""
    client = ab_env["client"]
    ref1, ref2 = _seed_two_hits(ab_env)
    marked = client.post(
        FEEDBACK_PATH,
        json={"query": "评注", "entryRef": ref1, "verdict": "useful", "reason": "直接回答了问题"},
        headers=ab_env["a"],
    )
    assert marked.status_code == 201, marked.text
    assert marked.json()["already"] is False
    assert (
        client.post(
            FEEDBACK_PATH,
            json={"query": "评注", "entryRef": ref2, "verdict": "irrelevant"},
            headers=ab_env["a"],
        ).status_code
        == 201
    )
    # 重标覆盖（同一 query+ref 唯一）。
    overwrite = client.post(
        FEEDBACK_PATH,
        json={"query": "评注", "entryRef": ref1, "verdict": "useful", "reason": "补充原因"},
        headers=ab_env["a"],
    )
    assert overwrite.status_code == 201
    assert overwrite.json()["already"] is True

    listing = client.get(FEEDBACK_PATH, params={"q": "评注"}, headers=ab_env["a"]).json()
    assert listing["counts"] == {"useful": 1, "irrelevant": 1}

    # 默认搜索：仍按时间序（e2 在前），反馈未插手。
    search = client.get("/api/v1/search", params={"q": "评注"}, headers=ab_env["a"]).json()
    assert [item["entryRef"] for item in search["items"]] == [ref2, ref1]


def test_new370_scheme_opt_in_and_rerank(ab_env):  # noqa: F811
    """方案默认关闭；关闭时 reranked 诚实空表；显式启用后有用置顶。"""
    client = ab_env["client"]
    ref1, ref2 = _seed_two_hits(ab_env)
    client.post(
        FEEDBACK_PATH,
        json={"query": "评注", "entryRef": ref1, "verdict": "useful"},
        headers=ab_env["a"],
    )

    initial = client.get(SCHEME_PATH, headers=ab_env["a"]).json()
    assert initial["enabled"] is False
    closed = client.get(RERANKED_PATH, params={"q": "评注"}, headers=ab_env["a"]).json()
    assert closed["enabled"] is False
    assert closed["items"] == []

    enabled = client.post(SCHEME_PATH, json={"enabled": True}, headers=ab_env["a"])
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True

    reranked = client.get(RERANKED_PATH, params={"q": "评注"}, headers=ab_env["a"]).json()
    assert reranked["enabled"] is True
    refs = [item["entryRef"] for item in reranked["items"]]
    assert refs == [ref1, ref2]  # 有用置顶，其余保持原顺序
    assert reranked["items"][0]["boosted"] is True
    assert reranked["items"][1]["boosted"] is False

    # 显式停用即回到空表语义。
    client.post(SCHEME_PATH, json={"enabled": False}, headers=ab_env["a"])
    disabled = client.get(RERANKED_PATH, params={"q": "评注"}, headers=ab_env["a"]).json()
    assert disabled["enabled"] is False and disabled["items"] == []


def test_new370_validation(ab_env):  # noqa: F811
    client = ab_env["client"]
    bad_verdict = client.post(
        FEEDBACK_PATH,
        json={"query": "评注", "entryRef": "rss:x", "verdict": "meh"},
        headers=ab_env["a"],
    )
    assert bad_verdict.status_code == 422
    ghost = client.post(
        FEEDBACK_PATH,
        json={
            "query": "评注",
            "entryRef": encode_entry_ref('n370-ghost'),
            "verdict": "useful",
        },
        headers=ab_env["a"],
    )
    assert ghost.status_code == 404
    assert ghost.json()["error"]["type"] == "search_entry_not_found"


def test_new370_isolation(ab_env):  # noqa: F811
    """反馈与方案开关都是本人数据：A 启用方案不改 B 的状态与结果。"""
    client = ab_env["client"]
    ref1, ref2 = _seed_two_hits(ab_env)
    client.post(
        FEEDBACK_PATH,
        json={"query": "评注", "entryRef": ref1, "verdict": "useful"},
        headers=ab_env["a"],
    )
    client.post(SCHEME_PATH, json={"enabled": True}, headers=ab_env["a"])

    b_listing = client.get(FEEDBACK_PATH, params={"q": "评注"}, headers=ab_env["b"]).json()
    assert b_listing["items"] == []
    assert b_listing["counts"] == {"useful": 0, "irrelevant": 0}
    b_scheme = client.get(SCHEME_PATH, headers=ab_env["b"]).json()
    assert b_scheme["enabled"] is False
    b_reranked = client.get(RERANKED_PATH, params={"q": "评注"}, headers=ab_env["b"]).json()
    assert b_reranked["items"] == []
    # B 的条目不在 A 投影：A 的 ref 对 B 不可评注（404 同缺失语义）。
    assert (
        client.post(
            FEEDBACK_PATH,
            json={"query": "评注", "entryRef": ref1, "verdict": "useful"},
            headers=ab_env["b"],
        ).status_code
        == 404
    )
