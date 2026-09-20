"""F045 屏蔽规则服务端化 — CRUD 限额、首条命中、转义、跨页计数、负向契约。"""

import asyncio
from types import SimpleNamespace

import pytest

from lumirss.feed_filter_store import (
    FeedFilterRuleStore,
    FilterRuleInvalid,
    FilterRuleLimit,
    compile_rules_to_sql,
    first_matching_rule,
)
from lumirss.main import app


def _run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture()
def db():
    import tempfile

    from lumirss.storage import Database

    db = Database(tempfile.mkdtemp() + "/lumi.sqlite")
    _run(db.migrate())
    return db


def test_f045_validation_and_sql_escaping(db):
    """value 校验 + SQL 谓词转义（含 % _ 值）+ OR 连接。"""
    store = FeedFilterRuleStore(db)
    with pytest.raises(FilterRuleInvalid):
        _run(store.create_rule(feed_url="https://e.com/f", field="body", op="contains", value="x"))
    _run(store.create_rule(feed_url="https://e.com/f", field="title", op="contains", value="100%折扣_限时"))
    _run(store.create_rule(feed_url="https://e.com/f", field="author", op="equals", value="spam-bot"))
    predicate, params = compile_rules_to_sql(_run(store.list_rules("https://e.com/f")))
    assert predicate.count(" OR ") == 1
    assert params[0] == "%100\\%折扣\\_限时%"
    assert params[1] == "spam-bot"


def test_f045_first_match_and_disabled_rules(db):
    store = FeedFilterRuleStore(db)
    _run(store.create_rule(feed_url="https://e.com/f", field="title", op="contains", value="广告"))
    _run(store.create_rule(feed_url="https://e.com/f", field="author", op="equals", value="bot"))
    rules = _run(store.list_rules("https://e.com/f"))
    hit = first_matching_rule(rules, title="优惠广告来袭", author="bot")
    assert hit is not None and hit["value"] == "广告"  # 首条命中优先
    # 停用规则不屏蔽
    disabled = _run(store.update_rule(rules[0]["id"], enabled=False))
    assert disabled is not None and disabled["enabled"] is False
    rules = _run(store.list_rules("https://e.com/f"))
    assert first_matching_rule(rules, title="广告", author=None) is None


def test_f045_rule_limit_422(db):
    store = FeedFilterRuleStore(db)
    for i in range(20):
        _run(
            store.create_rule(
                feed_url="https://e.com/f", field="title", op="contains", value=f"规则{i}"
            )
        )
    with pytest.raises(FilterRuleLimit):
        _run(store.create_rule(feed_url="https://e.com/f", field="title", op="contains", value="第21条"))
    # 换一个来源不受影响
    rule = _run(store.create_rule(feed_url="https://e.com/g", field="title", op="contains", value="x"))
    assert rule is not None


def test_f045_entries_route_filtering_cross_page_include_hidden(client):
    """entries 服务端过滤：剔除+filteredCount、include_hidden 标记、跨页计数一致。"""
    store = FeedFilterRuleStore(app.state.db)
    _run(
        store.create_rule(
            feed_url="https://feed.example.com/tech", field="title", op="contains", value="赞助"
        )
    )

    def entry(ref, title, page):
        _ = page
        from lumirss.models import EntryListItem

        return EntryListItem(
            entryRef=f"ref-{ref}",
            title=title,
            feedTitle="Tech",
            author=None,
            url=None,
            publishedAt=None,
            read=False,
            starred=False,
            feedUrl="https://feed.example.com/tech",
            snippet=None,
        )

    pages = {
        1: [entry("a1", "赞助内容", 1), entry("a2", "正常文章", 1)],
        2: [entry("b1", "又一条赞助", 2), entry("b2", "深度评测", 2)],
    }
    conts = {1: "2", 2: None}

    class FakeAdapter:
        async def list_entries(self, **kwargs):
            page = 2 if kwargs.get("continuation") else 1
            return SimpleNamespace(items=pages[page], upstreamContinuation=conts[page])

    app.state.freshrss_adapter = FakeAdapter()

    page1 = client.get("/api/v1/entries")
    assert page1.status_code == 200
    body1 = page1.json()
    assert [i["title"] for i in body1["items"]] == ["正常文章"]
    assert body1["filteredCount"] == 1

    # 跨页计数一致：第二页同样剔除且如实计数
    page2 = client.get("/api/v1/entries", params={"cursor": body1["nextCursor"]})
    assert page2.status_code == 200
    body2 = page2.json()
    assert [i["title"] for i in body2["items"]] == ["深度评测"]
    assert body2["filteredCount"] == 1

    # include_hidden=true 临时包含（带标记）
    hidden_view = client.get("/api/v1/entries", params={"includeHidden": "true"})
    items = hidden_view.json()["items"]
    assert len(items) == 2
    marked = [i for i in items if i["hiddenByRule"] is not None]
    assert len(marked) == 1
    assert "赞助" in marked[0]["hiddenByRule"]["reason"]


def test_f045_freshrss_state_untouched_negative(client):
    """负向：规则命中不影响 FreshRSS 侧（不调用 set-read/star；条目仍可访问）。"""
    store = FeedFilterRuleStore(app.state.db)
    _run(
        store.create_rule(
            feed_url="https://feed.example.com/tech", field="title", op="contains", value="赞助"
        )
    )

    class FakeAdapter:
        def __init__(self):
            self.state_calls: list = []

        async def list_entries(self, **kwargs):
            return SimpleNamespace(
                items=[
                    SimpleNamespace(
                        entryRef="ref-x",
                        title="赞助内容",
                        feedTitle="Tech",
                        author=None,
                        url=None,
                        publishedAt=None,
                        read=False,
                        starred=False,
                        feedUrl="https://feed.example.com/tech",
                        snippet=None,
                    )
                ],
                upstreamContinuation=None,
            )

        async def set_entry_state(self, entry_ref, read=None, starred=None):
            self.state_calls.append((entry_ref, read, starred))
            return True

    adapter = FakeAdapter()
    app.state.freshrss_adapter = adapter
    body = client.get("/api/v1/entries").json()
    assert body["items"] == [] and body["filteredCount"] == 1
    assert adapter.state_calls == []  # 服务端未产生任何状态写入


def test_f045_trial_endpoint(client):
    store = FeedFilterRuleStore(app.state.db)
    rule = _run(
        store.create_rule(
            feed_url="https://feed.example.com/tech", field="title", op="contains", value="赞助"
        )
    )
    hit = client.post(
        "/api/v1/feed-filter-rules/trial",
        json={"feedUrl": "https://feed.example.com/tech", "sampleTitle": "这是一条赞助推广"},
    )
    assert hit.status_code == 200
    body = hit.json()
    assert body["matched"] is True and body["ruleId"] == rule["id"]
    assert "赞助" in body["reason"]
    miss = client.post(
        "/api/v1/feed-filter-rules/trial",
        json={"feedUrl": "https://feed.example.com/tech", "sampleTitle": "普通标题"},
    )
    assert miss.json()["matched"] is False
