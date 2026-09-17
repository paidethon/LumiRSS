"""F04 收藏/稍后读转简报 — 保存类材料源测试。

- read_later：稍后读队列成员 → 逐条取正文 → 生成的引用只含队列内容；
- starred：greader starred 视图首页 → 同上；
- 生成过程只读：不改变已读/收藏/队列成员状态；
- saved 源不受时间窗口/白名单约束（语义不同，见 0031 注释）。
"""

import asyncio
from datetime import UTC, datetime

from lumirss.adapters.freshrss import EntryDetail
from lumirss.entryref import encode_entry_ref
from lumirss.gpt_digest import DigestMaterialEmpty, generate_issue
from lumirss.gpt_digest_configs import GptDigestConfigStore
from lumirss.gpt_digest_issues import GptDigestIssuesStore
from lumirss.main import app


def run(coroutine):
    return asyncio.run(coroutine)


UTC_ = UTC


def _detail(entry_ref: str, title: str, content: str) -> EntryDetail:
    return EntryDetail(
        entryRef=entry_ref,
        title=title,
        feedTitle="保存源",
        author=None,
        url=f"https://saved.example.com/{title}",
        publishedAt="2026-09-01T00:00:00Z",
        read=True,  # 已读过的旧文——saved 源不看时间窗
        starred=False,
        contentText=content,
        contentHtml=f"<p>{content}</p>",
    )


class _SavedAdapter:
    """list_entries(starred) 返回列表；get_entry 按 ref 返回详情。"""

    def __init__(self, starred_items: list[dict], details: dict[str, EntryDetail]):
        self._starred = starred_items
        self._details = details
        self.reads: list[str] = []

    async def list_entries(self, *, view="all", limit=None, **_):
        assert view in ("all", "starred")
        items = []
        if view == "starred":
            items = [
                SimpleEntry(ref=r, title=self._details[r].title)
                for r in self._starred
                if r in self._details
            ]
        return SimplePage(items=items)

    async def get_entry(self, item_id: str):
        entry_ref = encode_entry_ref(item_id)
        self.reads.append(entry_ref)
        return self._details[entry_ref]


class SimpleEntry:
    def __init__(self, ref: str, title: str):
        self.entryRef = ref
        self.title = title


class SimplePage:
    def __init__(self, items):
        self.items = items


_CONFIG = {
    "id": 2,
    "name": "保存简报",
    "enabled": True,
    "hour": 8,
    "timezone": "UTC",
    "windowHours": 24,
    "limitCount": 10,
    "perSourceCap": 0,
    "feedUrlAllow": "",
    "sourceKind": "read_later",
}


class _FakeAiSettings:
    async def load(self):
        return {"ai.base_url": "http://ai.local", "ai.model": "test-model"}


class _FakeProvider:
    def __init__(self, raw: str):
        self._raw = raw
        self.calls = 0

    async def complete(self, *, messages):
        self.calls += 1
        return self._raw


def _ok(provider):
    async def factory(base_url, model):
        return provider

    return factory


def _fixed_now():
    return datetime(2026, 9, 18, 8, 5, 0, tzinfo=UTC_)


def test_f04_read_later_briefing_generation(client):
    entry_ref = "e1.MDAwNjU5ZTA3YWFlZTI0ZA"
    joined = client.post(
        "/api/v1/workspaces/read-later/items",
        json={"itemRef": f"rss:{entry_ref}"},
    )
    assert joined.status_code in (200, 201), joined.text

    detail = _detail(entry_ref, "保存的文章", "稍后读内容正文。")
    adapter = _SavedAdapter(starred_items=[], details={entry_ref: detail})

    config = dict(_CONFIG)
    configs = GptDigestConfigStore(app.state.db)
    issues = GptDigestIssuesStore(app.state.db)
    provider = _FakeProvider(
        '{"title":"队列简报","sections":[{"heading":"主题","items":[{"summary":"总结。","sourceIds":["s1"],"uncertainty":null}]}],"limitations":[]}'
    )
    row = run(
        generate_issue(
            configs,
            issues,
            config=config,
            adapter=adapter,
            ai_settings=_FakeAiSettings(),
            provider_factory=_ok(provider),
            db=app.state.db,
            now=_fixed_now(),
        )
    )
    assert row["issue_key"] == "2026-09-18"
    assert adapter.reads == [entry_ref]
    # 只读承诺：取正文不改变已读状态
    assert detail.read is True


def test_f04_starred_source_and_empty_guard(client):
    ref = encode_entry_ref("000659e07aaee24d")
    detail = _detail(ref, "收藏文章", "收藏正文。")
    adapter = _SavedAdapter(starred_items=[ref], details={ref: detail})
    config = dict(_CONFIG)
    config["sourceKind"] = "starred"
    provider = _FakeProvider(
        '{"title":"收藏简报","sections":[{"heading":"主题","items":[{"summary":"s","sourceIds":["s1"],"uncertainty":null}]}],"limitations":[]}'
    )
    issues = GptDigestIssuesStore(app.state.db)
    row = run(
        generate_issue(
            GptDigestConfigStore(app.state.db),
            issues,
            config=config,
            adapter=adapter,
            ai_settings=_FakeAiSettings(),
            provider_factory=_ok(provider),
            db=app.state.db,
            now=_fixed_now(),
        )
    )
    assert row["title"] == "收藏简报"

    # 空收藏 → 不生成空简报
    empty_adapter = _SavedAdapter(starred_items=[], details={})
    try:
        run(
            generate_issue(
                GptDigestConfigStore(app.state.db),
                issues,
                config=config,
                adapter=empty_adapter,
                ai_settings=_FakeAiSettings(),
                provider_factory=_ok(_FakeProvider("{}")),
                db=app.state.db,
                now=_fixed_now(),
            )
        )
    except DigestMaterialEmpty:
        pass
    else:
        raise AssertionError("empty saved source should raise")
