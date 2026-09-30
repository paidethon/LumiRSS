"""NEW-364 作者与来源交叉筛选 — author 进核心搜索链 / facet 真实计数 / 隔离。"""

import asyncio

from lumirss.entryref import encode_entry_ref
from new2xx_ab import ab_env, seed_entry  # noqa: F401 — pytest 夹具注册

FACET_PATH = "/api/v1/search/author-source"
SEARCH_PATH = "/api/v1/search"


def _seed_cross(env, who: str = "a") -> None:
    """两作者 × 两来源的交叉命中（词条「光栅」全部命中）。"""

    async def run():
        from lumirss.user_scope import user_context

        rows = [
            ("n364-1", "光栅 报告一", "王研究", "https://a.example/rss", "源甲"),
            ("n364-2", "光栅 报告二", "王研究", "https://a.example/rss", "源甲"),
            ("n364-3", "光栅 通讯三", "李通讯", "https://b.example/rss", "源乙"),
            ("n364-4", "无关条目", "李通讯", "https://b.example/rss", "源乙"),
        ]
        with user_context(env[who]["userId"]):
            await env["app"].state.db.migrate()
            for item_id, title, author, feed_url, feed_title in rows:
                await env["app"].state.db.execute(
                    "INSERT OR IGNORE INTO search_entries (item_id, entry_ref,"
                    " feed_url, feed_title, title, author, url, content_text,"
                    " published_at, read, starred, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, 'u', '',"
                    " '2026-09-10T00:00:00Z', 0, 0, 0)",
                    (item_id, encode_entry_ref(item_id), feed_url, feed_title, title, author),
                )

    asyncio.run(run())


def test_new364_facets_show_real_counts(ab_env):  # noqa: F811
    """facet 计数来自实际命中：作者/来源各自展示组合后的真实数量。"""
    client = ab_env["client"]
    _seed_cross(ab_env)
    payload = client.get(
        f"{FACET_PATH}?q=光栅", headers=ab_env["a"]
    ).json()
    authors = {item["author"]: item["count"] for item in payload["authors"]}
    assert authors == {"王研究": 2, "李通讯": 1}
    sources = {item["feedTitle"]: item["count"] for item in payload["sources"]}
    assert sources == {"源甲": 2, "源乙": 1}
    assert payload["total"] == 3
    assert payload["authorsComplete"] is True

    # 交叉组合：选「王研究 × 源乙」→ 0；「王研究 × 源甲」→ 2。
    cross_zero = client.get(
        f"{FACET_PATH}?q=光栅&author=王研究&feedUrl=https://b.example/rss",
        headers=ab_env["a"],
    ).json()
    assert cross_zero["total"] == 0
    cross_two = client.get(
        f"{FACET_PATH}?q=光栅&author=王研究&feedUrl=https://a.example/rss",
        headers=ab_env["a"],
    ).json()
    assert cross_two["total"] == 2


def test_new364_author_filter_in_core_search(ab_env):  # noqa: F811
    """author 参数进入核心 GET /search：命中只剩该作者；翻页不漂移。"""
    client = ab_env["client"]
    _seed_cross(ab_env)
    page = client.get(
        f"{SEARCH_PATH}?q=光栅&author=王研究&limit=1", headers=ab_env["a"]
    )
    assert page.status_code == 200, page.text
    body = page.json()
    assert len(body["items"]) == 1
    assert all(item["author"] == "王研究" for item in body["items"])
    assert body["hasMore"] is True and body["nextCursor"]

    page2 = client.get(
        f"{SEARCH_PATH}?q=光栅&author=王研究&limit=10&cursor={body['nextCursor']}",
        headers=ab_env["a"],
    )
    assert page2.status_code == 200
    combined = [item["entryRef"] for item in body["items"]] + [
        item["entryRef"] for item in page2.json()["items"]
    ]
    assert len(combined) == 2  # 作者过滤后的全部命中，翻页不重不漏

    # scope 绑定：换作者续接同一 cursor → 400（不静默漂移）。
    swapped = client.get(
        f"{SEARCH_PATH}?q=光栅&author=李通讯&limit=10&cursor={body['nextCursor']}",
        headers=ab_env["a"],
    )
    assert swapped.status_code == 400


def test_new364_isolation(ab_env):  # noqa: F811
    client = ab_env["client"]
    _seed_cross(ab_env)
    b_facet = client.get(f"{FACET_PATH}?q=光栅", headers=ab_env["b"]).json()
    assert b_facet["total"] == 0
    assert b_facet["authors"] == [] and b_facet["sources"] == []
    b_search = client.get(
        f"{SEARCH_PATH}?q=光栅&author=王研究", headers=ab_env["b"]
    ).json()
    assert b_search["items"] == []
