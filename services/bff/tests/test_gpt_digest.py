"""GPT 日报（M4）单元与 API 测试。

覆盖：确定性选材（窗口/去重/自有 feed 排除/上限）、输出严格校验
（坏 JSON / 幽灵引用 / 非法形状）、渲染转义、store 校验与 token 轮换、
issue upsert 幂等（同日期=修订不新增行）、调度幂等（固定时钟）、
API settings 往返、Atom 订阅（token 常量时间、304、GET 不触发生成）。
真实 GPT 调用一律用本地协议假件替代（费用边界）。"""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from lumirss.adapters.freshrss import EntryDocument, EntryDocumentPage
from lumirss.gpt_digest import (
    DigestMaterialEmpty,
    DigestOutputInvalid,
    GptDigestScheduler,
    generate_issue,
    parse_and_validate_output,
    render_issue_html,
    select_material,
)
from lumirss.gpt_digest_issues import GptDigestIssuesStore
from lumirss.gpt_digest_store import GptDigestStore, issue_key_for
from lumirss.main import app


def run(coroutine):
    return asyncio.run(coroutine)


UTC = UTC


def _store():
    return GptDigestStore(app.state.db, app.state.secrets_store)


def _issues_store():
    return GptDigestIssuesStore(app.state.db, _store())


def _doc(item_id: str, published: str, feed_url: str = "https://blog.example.com/rss") -> dict:
    return {
        "item_id": item_id,
        "entryRef": f"ref-{item_id}",
        "feedUrl": feed_url,
        "feedTitle": "示例源",
        "title": f"文章 {item_id}",
        "url": f"https://blog.example.com/{item_id}",
        "publishedAt": published,
        "read": False,
        "starred": False,
        "contentText": f"{item_id} 的正文内容。",
    }


def test_select_material_window_dedupe_and_self_exclusion():
    start = "2026-09-17T00:00:00+00:00"
    end = "2026-09-18T00:00:00+00:00"
    docs = [
        _doc("a", "2026-09-17T05:00:00+00:00"),
        _doc("b", "2026-09-17T23:30:00+00:00"),
        # 窗口外：早于 start / 晚于等于 end
        _doc("old", "2026-09-16T23:59:59+00:00"),
        _doc("future", end),
        # 本实例生成的 feed：绝不作为输入（防递归日报）
        _doc("self", "2026-09-17T10:00:00+00:00", feed_url="https://rss.example.com/feeds/gpt-digest/tok.atom"),
        _doc("mail", "2026-09-17T10:05:00+00:00", feed_url="https://rss.example.com/feeds/mail/uuid.secret.atom"),
        # 重复 item_id
        _doc("a", "2026-09-17T05:00:00+00:00"),
    ]
    chosen = select_material(docs, start, end, limit=10)
    ids = [d["item_id"] for d in chosen]
    assert ids == ["b", "a"], ids  # 时间倒序、去重、窗口、自有 feed 排除
    capped = select_material(docs, start, end, limit=1)
    assert [d["item_id"] for d in capped] == ["b"]


def test_parse_and_validate_happy_and_garbage():
    valid = ["s1", "s2"]
    raw = json.dumps(
        {
            "title": "日报",
            "sections": [
                {
                    "heading": "主题",
                    "items": [{"summary": "总结。", "sourceIds": ["s1"], "uncertainty": None}],
                }
            ],
            "limitations": ["材料有限"],
        },
        ensure_ascii=False,
    )
    parsed = parse_and_validate_output(f"```json\n{raw}\n```", valid)
    assert parsed["title"] == "日报"
    assert parsed["limitations"] == ["材料有限"]

    for bad in [
        "not json",
        json.dumps({"title": "x", "sections": []}),
        json.dumps({"title": "x", "sections": [{"heading": "h", "items": [{"summary": "s", "sourceIds": ["ghost"]}]}]}),
        json.dumps({"title": "x", "sections": [{"heading": "h", "items": [{"summary": "", "sourceIds": ["s1"]}]}]}),
        json.dumps({"sections": [{"heading": "h", "items": [{"summary": "s", "sourceIds": ["s1"]}]}]}),
        json.dumps({"title": "x", "sections": "nope"}),
    ]:
        try:
            parse_and_validate_output(bad, valid)
        except DigestOutputInvalid:
            continue
        raise AssertionError(f"should have rejected: {bad}")


def test_render_issue_html_escapes_and_resolves_links_from_refs():
    output = {
        "title": "标题 <script>",
        "sections": [
            {
                "heading": "主题 & <b>",
                "items": [
                    {
                        "summary": "要点 <img onerror=x>",
                        "sourceIds": ["s1"],
                        "uncertainty": None,
                    }
                ],
            }
        ],
        "limitations": [],
    }
    refs = {
        "s1": {
            "title": "文章",
            "url": "https://blog.example.com/a",
            "feedTitle": "示例源",
            "publishedAt": "2026-09-17T05:00:00+00:00",
        }
    }
    html = render_issue_html(output, refs)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert '<a href="https://blog.example.com/a">示例源</a>' in html


def test_store_defaults_clamps_and_timezone_fallback(client):
    store = _store()
    saved = run(store.save({"hour": 99, "windowHours": 999, "limitCount": 0}))
    assert saved["hour"] == 8  # 非法 hour 回退现值（与 mail digest 同一风格）
    assert saved["windowHours"] == 72  # 窗口/上限做范围收敛
    assert saved["limitCount"] == 1
    saved = run(store.save({"timezone": "Mars/Olympus"}))
    assert saved["timezone"] == ""  # 非法名保留现值（当前为空）
    saved = run(store.save({"timezone": "Asia/Shanghai"}))
    assert saved["timezone"] == "Asia/Shanghai"


def test_feed_token_roundtrip(client):
    store = _store()
    token = store.ensure_feed_token()
    assert token and store.feed_token() == token
    rotated = store.rotate_feed_token()
    assert rotated != token
    assert store.feed_token() == rotated


def test_issue_upsert_is_revision_not_duplicate(client):
    issues = _issues_store()
    first = run(
        issues.upsert_issue(
            issue_key="2026-09-18",
            title="v1",
            body_html="<p>v1</p>",
            sections_json="[]",
            refs_json="{}",
            model="m",
            published_at="2026-09-18T00:00:00+00:00",
        )
    )
    second = run(
        issues.upsert_issue(
            issue_key="2026-09-18",
            title="v2",
            body_html="<p>v2</p>",
            sections_json="[]",
            refs_json="{}",
            model="m",
            published_at="2026-09-18T00:00:00+00:00",
        )
    )
    assert first["issue_key"] == second["issue_key"]
    assert second["title"] == "v2"
    assert second["published_at"] == "2026-09-18T00:00:00+00:00"  # 首发时刻保留
    recent = run(issues.recent_issues(10))
    assert len(recent) == 1
    dto = issues.issue_to_dto(recent[0])
    assert dto["issueKey"] == "2026-09-18"


class _FakeAdapter:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    async def list_entry_documents(self, limit: int = 120):
        return EntryDocumentPage(
            documents=[EntryDocument(**d) for d in self._docs],
            upstreamContinuation=None,
        )


class _FakeAiSettings:
    async def load(self):
        return {"ai.base_url": "http://ai.local", "ai.model": "test-model"}


class _FakeProvider:
    def __init__(self, raw: str):
        self._raw = raw
        self.calls = 0

    async def complete(self, *, messages):
        self.calls += 1
        assert messages[0]["role"] == "system"
        return self._raw


def _material_output(material_ids: list[str]) -> str:
    return json.dumps(
        {
            "title": "测试日报",
            "sections": [
                {
                    "heading": "主题",
                    "items": [
                        {"summary": f"关于 {sid}。", "sourceIds": [sid], "uncertainty": None}
                        for sid in material_ids
                    ],
                }
            ],
            "limitations": [],
        },
        ensure_ascii=False,
    )


def _fixed_now() -> datetime:
    return datetime(2026, 9, 18, 8, 5, 0, tzinfo=UTC)


def test_generate_issue_success_marks_and_persists(client):
    docs = [_doc("a", "2026-09-18T00:10:00+00:00")]
    store = _store()
    issues = _issues_store()
    provider = _FakeProvider(_material_output(["s1"]))
    row = run(
        generate_issue(
            store,
            issues,
            adapter=_FakeAdapter(docs),
            ai_settings=_FakeAiSettings(),
            provider_factory=_ok(provider),
            settings={
                "timezone": "UTC",
                "windowHours": 24,
                "limitCount": 10,
                "hour": 8,
                "enabled": True,
            },
            now=_fixed_now(),
        )
    )
    assert row["issue_key"] == "2026-09-18"
    assert row["body_html"].startswith("<h2>")
    saved = run(store.load())
    assert saved["lastIssueKey"] == "2026-09-18"
    assert saved["lastError"] is None


def _ok(provider):
    async def factory(base_url, model):
        return provider

    return factory


def test_generate_issue_empty_window_keeps_previous_issue(client):
    store = _store()
    issues = _issues_store()
    run(
        issues.upsert_issue(
            issue_key="2026-09-17",
            title="上一份",
            body_html="<p>ok</p>",
            sections_json="[]",
            refs_json="{}",
            model="m",
            published_at="2026-09-17T00:00:00+00:00",
        )
    )
    provider = _FakeProvider("{}")
    try:
        run(
            generate_issue(
                store,
                issues,
                adapter=_FakeAdapter([]),
                ai_settings=_FakeAiSettings(),
                provider_factory=_ok(provider),
                settings={"timezone": "UTC", "windowHours": 24, "limitCount": 10, "hour": 8, "enabled": True},
                now=_fixed_now(),
            )
        )
    except DigestMaterialEmpty:
        pass
    else:
        raise AssertionError("empty window should raise")
    assert provider.calls == 0, "没有材料时不发生任何模型调用"
    assert run(issues.recent_issues(10))[0]["title"] == "上一份"
    assert "没有可用材料" in (run(store.load())["lastError"] or "")


def test_generate_issue_invalid_output_never_publishes(client):
    docs = [_doc("a", "2026-09-18T00:10:00+00:00")]
    store = _store()
    issues = _issues_store()
    provider = _FakeProvider(
        '{"title":"x","sections":[{"heading":"h","items":[{"summary":"s","sourceIds":["ghost"]}]}]}'
    )
    with pytest.raises(DigestOutputInvalid):
        run(
            generate_issue(
                store,
                issues,
                adapter=_FakeAdapter(docs),
                ai_settings=_FakeAiSettings(),
                provider_factory=_ok(provider),
                settings={"timezone": "UTC", "windowHours": 24, "limitCount": 10, "hour": 8, "enabled": True},
                now=_fixed_now(),
            )
        )
    assert run(issues.recent_issues(10)) == []
    assert "来源编号" in (run(store.load())["lastError"] or "")


def test_scheduler_idempotent_across_restarts_with_fixed_clock(client):
    store = _store()
    run(store.save({"enabled": True, "hour": 8, "timezone": "UTC"}))
    generated = []
    clock_now = _fixed_now()

    async def generate_fn():
        generated.append(clock_now.date().isoformat())
        return {"issue_key": "2026-09-18"}

    scheduler = GptDigestScheduler(store._db, clock=lambda _tz: clock_now)
    first = run(scheduler.maybe_generate(generate_fn, run(store.load())))
    assert first == {"issue_key": "2026-09-18"}
    # 重启（新 scheduler 实例）+ 同一天 → 幂等不重跑
    scheduler2 = GptDigestScheduler(store._db, clock=lambda _tz: clock_now)
    run(store.mark_published("2026-09-18"))
    assert run(scheduler2.maybe_generate(generate_fn, run(store.load()))) is None
    assert generated == ["2026-09-18"]
    # 错过 08:00、09:30 重启的同日补跑由 lastIssueKey 阻止；非到期小时也不触发
    later = _fixed_now() + timedelta(hours=2)
    scheduler3 = GptDigestScheduler(store._db, clock=lambda _tz: later)
    assert run(scheduler3.maybe_generate(generate_fn, run(store.load()))) is None


def test_issue_key_uses_configured_timezone():
    now = datetime(2026, 9, 18, 16, 0, 0, tzinfo=UTC)  # 北京时间 9-19 00:00
    assert issue_key_for(now, "UTC") == "2026-09-18"
    assert issue_key_for(now, "Asia/Shanghai") == "2026-09-19"


def test_api_settings_roundtrip_and_atom_subscription(client):
    response = client.put(
        "/api/v1/gpt-digest/settings",
        json={"enabled": True, "hour": 7, "timezone": "UTC", "windowHours": 12, "limitCount": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["windowHours"] == 12

    feed = client.get("/api/v1/gpt-digest/feed").json()
    atom_path = feed["atomPath"]
    assert atom_path.startswith("/feeds/gpt-digest/")
    # 未生成期刊：仍是合法空 feed（updated=当前时刻），而不是 500
    empty = client.get(atom_path)
    assert empty.status_code == 200
    assert b"<feed" in empty.content

    # 种一期 → 订阅可见；ETag 304 稳定
    issues = _issues_store()
    run(
        issues.upsert_issue(
            issue_key="2026-09-18",
            title="订阅可见的一期",
            body_html="<p>正文</p>",
            sections_json="[]",
            refs_json="{}",
            model="m",
            published_at="2026-09-18T00:00:00+00:00",
        )
    )
    ok = client.get(atom_path)
    assert ok.status_code == 200
    assert "订阅可见的一期" in ok.text
    assert "urn:lumirss:gptdigest:2026-09-18" in ok.text
    etag = ok.headers["ETag"]
    not_modified = client.get(atom_path, headers={"If-None-Match": etag})
    assert not_modified.status_code == 304

    # token 错误 → 404；列表接口不带正文
    assert client.get("/feeds/gpt-digest/wrong-token.atom").status_code == 404
    listing = client.get("/api/v1/gpt-digest/issues").json()
    assert listing["items"][0]["title"] == "订阅可见的一期"
