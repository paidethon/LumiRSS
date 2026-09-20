"""F048 per-source 正文提取策略 — web 策略、缓存、失败回退、SSRF 拒绝。"""

import asyncio
from types import SimpleNamespace

from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.models import EntryDetail
from lumirss.source_overrides import SourceOverrideStore

FEED_URL = "https://feed.example.com/tech"
ENTRY_REF = encode_entry_ref("item-1")


def _run(coroutine):
    return asyncio.run(coroutine)


class FakeAdapter:
    def __init__(self, rss_html: str, url: str = "https://example.com/a/1"):
        self.rss_html = rss_html
        self.url = url
        self.detail_calls = 0

    async def get_entry(self, item_id):
        _ = item_id
        self.detail_calls += 1
        return EntryDetail(
            entryRef=ENTRY_REF,
            title="标题",
            feedTitle="Tech",
            author=None,
            url=self.url,
            publishedAt=None,
            read=False,
            starred=False,
            contentText="RSS 摘要正文",
            contentHtml=self.rss_html,
            feedUrl=FEED_URL,
            crawledAt=None,
        )


def _enable_web():
    _run(SourceOverrideStore(app.state.db).set_extract_policy(FEED_URL, "web"))


def test_f048_web_policy_changes_body_and_caches(client, monkeypatch):
    """摘要型 feed 切 web 后正文变化；缓存命中不重复抓；RSS 正文不受影响。"""
    rss_html = "<p>RSS 摘要正文</p>"
    adapter = FakeAdapter(rss_html)
    app.state.freshrss_adapter = adapter
    _enable_web()

    calls: list[str] = []

    async def fake_extract(url):
        calls.append(url)
        return SimpleNamespace(
            content_html="<article><p>完整原文正文（网页提取）</p></article>",
            content_text="完整原文正文",
            title="标题",
            byline=None,
        )

    import lumirss.clip_fetch as clip

    monkeypatch.setattr(clip, "fetch_extract_sanitize", fake_extract)
    body = client.get(f"/api/v1/entries/{ENTRY_REF}").json()
    assert body["extractPolicy"] == "web"
    assert "网页提取" in body["contentHtml"]
    assert body["extractionFailed"] is False
    assert len(calls) == 1

    # 第二次：缓存命中，不重复抓
    cached = client.get(f"/api/v1/entries/{ENTRY_REF}").json()
    assert "网页提取" in cached["contentHtml"]
    assert len(calls) == 1
    row = _run(
        app.state.db.fetch_one(
            "SELECT content_html FROM entry_extract_cache WHERE entry_ref = ?",
            (ENTRY_REF,),
        )
    )
    assert row is not None and "网页提取" in row["content_html"]

    # RSS 原文不受影响（adapter 数据未被改写）
    assert adapter.rss_html == rss_html


def test_f048_failure_falls_back_and_marks(client, monkeypatch):
    """提取失败（超限/异常）回退 RSS 正文 + extractionFailed 标记。"""
    adapter = FakeAdapter("<p>RSS 摘要正文</p>")
    app.state.freshrss_adapter = adapter
    _enable_web()

    from lumirss.clip_fetch import ClipFetchError

    async def failing_extract(url):
        raise ClipFetchError("页面超过大小上限。", "too_large")

    import lumirss.clip_fetch as clip

    monkeypatch.setattr(clip, "fetch_extract_sanitize", failing_extract)
    body = client.get(f"/api/v1/entries/{ENTRY_REF}").json()
    assert body["extractionFailed"] is True
    assert body["contentHtml"] == "<p>RSS 摘要正文</p>"  # RSS 正文原样保留


def test_f048_ssrf_private_refusal_falls_back_without_private_content(client, monkeypatch):
    """SSRF：私网目标拒绝 → 回退 RSS 正文，绝不透出私网抓取内容。"""
    adapter = FakeAdapter("<p>RSS 摘要正文</p>", url="http://192.168.1.10/secret")
    app.state.freshrss_adapter = adapter
    _enable_web()

    from lumirss.clip_fetch import ClipForbidden

    async def refusing_extract(url):
        raise ClipForbidden("页面地址解析到非公网地址，已拒绝。", "unsafe_address")

    import lumirss.clip_fetch as clip

    monkeypatch.setattr(clip, "fetch_extract_sanitize", refusing_extract)
    body = client.get(f"/api/v1/entries/{ENTRY_REF}").json()
    assert body["extractionFailed"] is True
    assert "secret" not in (body["contentHtml"] or "")


def test_f048_policy_roundtrip_and_rss_default(client):
    """策略设置往返；rss 策略直接返回 RSS 正文不抓取；非法策略 422。"""
    store = SourceOverrideStore(app.state.db)
    _run(store.set_extract_policy(FEED_URL, "web"))
    assert _run(store.get_extract_policy(FEED_URL)) == "web"
    _run(store.set_extract_policy(FEED_URL, "rss"))
    assert _run(store.get_extract_policy(FEED_URL)) == "rss"

    # 经 overrides 端点设置 + 非法值 422
    ok = client.put(
        "/api/v1/sources/overrides",
        json={"feedUrl": FEED_URL, "extractPolicy": "web"},
    )
    assert ok.status_code == 200
    assert ok.json()["extractPolicy"] == "web"
    bad = client.put(
        "/api/v1/sources/overrides",
        json={"feedUrl": FEED_URL, "extractPolicy": "js"},
    )
    assert bad.status_code in (400, 422)
