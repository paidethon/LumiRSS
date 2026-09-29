"""NEW-313 剪藏正文候选对照 — 双策略候选、选择应用（锚点不动）、诚实失败、A/B 隔离。

fetch 全部 mock（真源口径见 clip_fetch 管线测试）；本套件验证对照层。
"""

import asyncio
import uuid as _uuid
from dataclasses import dataclass

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册

CLIP_URL = "https://longform.example/posts/deep-dive"

RAW_HTML = (
    "<html><head><title>深度长文</title></head><body>"
    "<nav><a href='/home'>首页</a><a href='/tags'>标签</a></nav>"
    "<article>"
    "<p>这是评分法能抓住的正文第一段，句子足够长并且带有标点符号，用于评分。</p>"
    "<p>正文第二段：继续讲述完整内容，保证段落评分足够高。</p>"
    "</article>"
    "<footer>页脚噪音：相关推荐 隐私政策 广告位</footer>"
    "</body></html>"
)


@dataclass
class _Page:
    html: str
    final_url: str
    content_type: str = "text/html"


def _fake_fetcher(calls: list[str]):
    async def fetch(url: str):
        calls.append(url)
        return _Page(html=RAW_HTML, final_url=url)

    return fetch


def _failing_fetcher():
    from lumirss.clip_fetch import ClipFetchError

    async def fetch(url: str):
        raise ClipFetchError("页面返回 HTTP 404。", "forbidden")

    return fetch


def _seed_clip(ab_env, who: str) -> str:  # noqa: F811
    clip_uuid = str(_uuid.uuid4())

    async def seed():
        from lumirss.user_scope import user_context

        with user_context(ab_env[who]["userId"]):
            db = ab_env["app"].state.db
            await db.migrate()
            await db.execute(
                "INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'clip', '2026-09-01T00:00:00Z')",
                (clip_uuid,),
            )
            await db.execute(
                "INSERT INTO library_clips (item_uuid, url, title, byline, content_html, content_text, fetched_at, created_at)"
                " VALUES (?, ?, '深度长文', NULL, '<article><p>原始版本</p></article>', '原始版本', '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')",
                (clip_uuid, CLIP_URL),
            )

    asyncio.run(seed())
    return clip_uuid


def _install_fetcher(ab_env, fetcher) -> None:  # noqa: F811
    """路由通过 app.state.extract_compare_fetcher 接受注入（生产为 None）。"""
    ab_env["app"].state.extract_compare_fetcher = fetcher


def _routes(ab_env, item_uuid: str):  # noqa: F811
    return {
        "compare": f"/api/v1/library/clips/{item_uuid}/extract-compare",
        "choose": lambda cid: (
            f"/api/v1/library/clips/{item_uuid}/extract-compare/{cid}/choose"
        ),
    }


def test_new313_two_candidates_from_one_fetch_and_choose_preserves_original(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    clip_uuid = _seed_clip(ab_env, "a")
    calls: list[str] = []
    _install_fetcher(ab_env, _fake_fetcher(calls))
    routes = _routes(ab_env, clip_uuid)

    compare = client.post(routes["compare"], headers=a)
    assert compare.status_code == 200, compare.text
    body = compare.json()
    # 一次抓取、两种候选
    assert calls == [CLIP_URL]
    strategies = [c["strategy"] for c in body["candidates"]]
    assert strategies == ["article", "fulltext"]
    article, fulltext = body["candidates"]
    # fulltext 保留页脚/导航噪音 → 更长；article 只剩正文
    assert fulltext["charCount"] > article["charCount"] > 0
    assert "页脚噪音" in fulltext["preview"] or fulltext["charCount"] > article["charCount"]
    assert all(c["chosen"] is False for c in body["candidates"])

    # 选择 article → 写修订槽；原始 content_html 不变、笔记锚点不动
    chosen = client.post(routes["choose"](article["id"]), headers=a)
    assert chosen.status_code == 200, chosen.text

    async def read_row():
        from lumirss.user_scope import user_context

        with user_context(a["userId"]):
            db = ab_env["app"].state.db
            return await db.fetch_one(
                "SELECT content_html, content_text, revised_note, revised_content_html FROM library_clips WHERE item_uuid = ?",
                (clip_uuid,),
            )

    row = asyncio.run(read_row())
    assert row is not None
    assert "原始版本" in str(row["content_html"])  # 原始版本保持可读
    assert "评分法" in str(row["revised_content_html"])  # 展示版本已切换
    assert row["revised_note"] is None  # 笔记锚点未被改写

    # 再对照：上次选择仍标记 chosen
    last = client.get(routes["compare"], headers=a)
    assert last.status_code == 200
    chosen_rows = [c for c in last.json()["candidates"] if c["chosen"]]
    assert len(chosen_rows) == 1 and chosen_rows[0]["strategy"] == "article"


def test_new313_honest_failure_when_original_unreachable(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    clip_uuid = _seed_clip(ab_env, "a")
    _install_fetcher(ab_env, _failing_fetcher())
    routes = _routes(ab_env, clip_uuid)

    failed = client.post(routes["compare"], headers=a)
    assert failed.status_code == 502
    assert failed.json()["error"]["type"] == "clip_fetch_failed"

    # 没有写入任何候选
    last = client.get(routes["compare"], headers=a)
    assert last.status_code == 404

    # 不存在的剪藏 → 404
    missing = client.post(
        f"/api/v1/library/clips/{_uuid.uuid4()}/extract-compare", headers=a
    )
    assert missing.status_code == 404


def test_new313_per_user_isolation_between_accounts(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    clip_uuid = _seed_clip(ab_env, "a")
    calls: list[str] = []
    _install_fetcher(ab_env, _fake_fetcher(calls))
    routes = _routes(ab_env, clip_uuid)

    compare = client.post(routes["compare"], headers=a)
    assert compare.status_code == 200
    candidate_id = compare.json()["candidates"][0]["id"]

    # B 视角：A 的剪藏与候选都不存在
    assert client.get(routes["compare"], headers=b).status_code == 404
    assert client.post(routes["choose"](candidate_id), headers=b).status_code == 404
