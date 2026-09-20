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
    classify_material,
    compare_facts,
    compare_with_previous,
    explain_issue,
    generate_issue,
    generate_weekly,
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
    return GptDigestIssuesStore(app.state.db)


def _doc(item_id: str, published: str, feed_url: str = "https://blog.example.com/rss") -> dict:
    base = feed_url.rsplit("/", 1)[0]
    return {
        "item_id": item_id,
        "entryRef": f"ref-{item_id}",
        "feedUrl": feed_url,
        "feedTitle": "示例源",
        "title": f"文章 {item_id}",
        "url": f"{base}/{item_id}",
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


def test_classify_material_reports_reasons_and_per_source_cap():
    start = "2026-09-17T00:00:00+00:00"
    end = "2026-09-18T00:00:00+00:00"
    docs = [
        dict(_doc("a", "2026-09-17T05:00:00+00:00"), feedTitle="源一"),
        dict(_doc("a2", "2026-09-17T06:00:00+00:00"), feedTitle="源一"),
        dict(_doc("a3", "2026-09-17T07:00:00+00:00"), feedTitle="源一"),
        dict(_doc("b", "2026-09-17T23:30:00+00:00"), feedTitle="源二"),
        _doc("old", "2026-09-16T23:59:59+00:00"),  # 窗口外
        _doc("self", "2026-09-17T10:00:00+00:00", feed_url="https://rss.example.com/feeds/gpt-digest/t.atom"),
        _doc("a", "2026-09-17T05:00:00+00:00"),  # 重复
    ]
    verdict = classify_material(docs, start, end, limit=10, per_source_cap=2)
    assert [d["item_id"] for d in verdict["selected"]] == ["b", "a3", "a2"]
    assert verdict["counts"]["outsideWindow"] == 1
    assert verdict["counts"]["selfFeed"] == 1
    assert verdict["counts"]["duplicate"] == 1
    assert verdict["counts"]["perSourceCapped"] == 1  # 源一第 3 条被截
    assert verdict["perSource"] == {"源一": 2, "源二": 1}
    # 总量上限=2 先于单源配额触发（后续条目计入 overLimit）
    verdict2 = classify_material(docs, start, end, limit=2, per_source_cap=2)
    assert [d["item_id"] for d in verdict2["selected"]] == ["b", "a3"]
    assert verdict2["counts"]["perSourceCapped"] == 0
    assert verdict2["counts"]["overLimit"] == 2
    # 配额为 0 = 不启用
    verdict3 = classify_material(docs, start, end, limit=10, per_source_cap=0)
    assert len(verdict3["selected"]) == 4


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
    """§13.4：secrets 文件只存 SHA-256——ensure/rotate 返回的原始 token
    与存储值不同但校验等价；轮换后旧 token 立即失效。"""
    from lumirss.token_hash import is_token_hash, verify_token

    store = _store()
    token = store.ensure_feed_token()
    assert token
    stored = store.feed_token()
    assert stored and is_token_hash(stored)  # 库（文件）里无明文
    assert verify_token(token, stored)  # 校验=sha256(呈递)==存储
    rotated = store.rotate_feed_token()
    assert rotated != token
    stored2 = store.feed_token()
    assert stored2 and is_token_hash(stored2) and stored2 != stored
    assert verify_token(rotated, stored2)
    assert not verify_token(token, stored2)  # 旧 token 失效


def test_issue_upsert_is_revision_not_duplicate(client):
    issues = _issues_store()
    first = run(
        issues.upsert_issue(
            config_id=1,
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
            config_id=1,
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
    recent = run(issues.recent_issues(1, 10))
    assert len(recent) == 1
    dto = issues.issue_to_dto(recent[0])
    assert dto["issueKey"] == "2026-09-18"


def test_f01_configs_crud_isolation_and_same_day_no_collision(client):
    """F01 验收：新增/编辑/暂停/删除；两份配置同日生成互不覆盖；
    来源白名单让材料互不串用；默认配置不可删除。"""
    configs = _config_store()
    issues = _issues_store()
    provider = _FakeProvider(_material_output(["s1"]))
    tech = run(
        configs.create_config(
            {"name": "技术日报", "timezone": "UTC", "feedUrlAllow": "tech.example.com"}
        )
    )
    oss = run(
        configs.create_config(
            {"name": "开源日报", "timezone": "UTC", "feedUrlAllow": "oss.example.org"}
        )
    )
    assert tech["enabled"] is False and oss["enabled"] is False  # 新配置默认 paused
    run(configs.update_config(tech["id"], {"enabled": True}))
    run(configs.update_config(oss["id"], {"enabled": True}))

    docs = [
        _doc("t1", "2026-09-18T00:10:00+00:00", feed_url="https://tech.example.com/rss"),
        _doc("o1", "2026-09-18T00:20:00+00:00", feed_url="https://oss.example.org/rss"),
    ]
    adapter = _FakeAdapter(docs)

    class _Bound:
        def __init__(self, cfg):
            self._cfg = cfg

        def __getattr__(self, name):
            return getattr(adapter, name)

        async def list_entry_documents(self, limit=120):
            return await adapter.list_entry_documents(limit)

    run(
        generate_issue(
            configs,
            issues,
            config=run(configs.get_config(tech["id"])),
            adapter=adapter,
            ai_settings=_FakeAiSettings(),
            provider_factory=_ok(provider),
            now=_fixed_now(),
        )
    )
    run(
        generate_issue(
            configs,
            issues,
            config=run(configs.get_config(oss["id"])),
            adapter=adapter,
            ai_settings=_FakeAiSettings(),
            provider_factory=_ok(provider),
            now=_fixed_now(),
        )
    )
    tech_issues = run(issues.recent_issues(tech["id"], 10))
    oss_issues = run(issues.recent_issues(oss["id"], 10))
    # 同一期号（同日）互不覆盖，且引用只含各自白名单内的来源
    assert tech_issues[0]["issue_key"] == oss_issues[0]["issue_key"] == "2026-09-18"
    tech_refs = json.loads(tech_issues[0]["refs_json"])
    oss_refs = json.loads(oss_issues[0]["refs_json"])
    assert all("tech.example.com" in ref["url"] for ref in tech_refs.values())
    assert all("oss.example.org" in ref["url"] for ref in oss_refs.values())

    # 暂停 = enabled false；删除级联期刊；默认配置不可删除
    paused = run(configs.update_config(tech["id"], {"enabled": False}))
    assert paused["enabled"] is False
    assert run(configs.delete_config(1)) is False
    assert run(configs.delete_config(tech["id"])) is True
    assert run(issues.recent_issues(tech["id"], 10)) == []
    assert run(issues.recent_issues(oss["id"], 10)), "其它配置的期刊不受级联影响"

    # API 面：列表 + 指定配置订阅路径 + 错误 token 404。
    # §13.4：首次 GET 创建 token 并一次性返回地址；再次 GET atomPath 为
    # 空（token 只存哈希，明文不可重建——诚实降级），公开 feed 照常可读。
    listing = client.get("/api/v1/gpt-digest/configs").json()
    assert {c["name"] for c in listing["items"]} >= {"默认日报", "开源日报"}
    atom_path = client.get("/api/v1/gpt-digest/feed").json()["atomPath"]
    assert atom_path.startswith("/feeds/gpt-digest/")
    token = atom_path.split("/")[-1][: -len(".atom")]
    assert client.get("/api/v1/gpt-digest/feed").json()["atomPath"] == ""
    oss_feed = f"/feeds/gpt-digest/{oss['id']}.{token}.atom"
    body = client.get(oss_feed)
    assert body.status_code == 200
    assert "开源日报" in body.text
    assert client.get(f"/feeds/gpt-digest/{oss['id']}.wrong.atom").status_code == 404


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


def _config_store():
    from lumirss.gpt_digest_configs import GptDigestConfigStore

    return GptDigestConfigStore(app.state.db)


_DEFAULT_CONFIG = {
    "id": 1,
    "name": "默认日报",
    "enabled": True,
    "timezone": "UTC",
    "windowHours": 24,
    "limitCount": 10,
    "hour": 8,
    "perSourceCap": 0,
    "feedUrlAllow": "",
}


def test_generate_issue_success_marks_and_persists(client):
    docs = [_doc("a", "2026-09-18T00:10:00+00:00")]
    store = _store()
    issues = _issues_store()
    provider = _FakeProvider(_material_output(["s1"]))
    row = run(
        generate_issue(
            _config_store(),
            issues,
            config=dict(_DEFAULT_CONFIG),
            adapter=_FakeAdapter(docs),
            ai_settings=_FakeAiSettings(),
            provider_factory=_ok(provider),
            db=app.state.db,
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
            config_id=1,
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
    with pytest.raises(DigestMaterialEmpty):
        run(
            generate_issue(
                _config_store(),
                issues,
                config=dict(_DEFAULT_CONFIG),
                adapter=_FakeAdapter([]),
                ai_settings=_FakeAiSettings(),
                provider_factory=_ok(provider),
                now=_fixed_now(),
            )
        )
    assert provider.calls == 0, "没有材料时不发生任何模型调用"
    assert run(issues.recent_issues(1, 10))[0]["title"] == "上一份"
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
                _config_store(),
                issues,
                config=dict(_DEFAULT_CONFIG),
                adapter=_FakeAdapter(docs),
                ai_settings=_FakeAiSettings(),
                provider_factory=_ok(provider),
                now=_fixed_now(),
            )
        )
    assert run(issues.recent_issues(1, 10)) == []
    assert "来源编号" in (run(store.load())["lastError"] or "")


def test_scheduler_idempotent_across_restarts_with_fixed_clock(client):
    store = _store()
    run(store.save({"enabled": True, "hour": 8, "timezone": "UTC"}))
    generated = []
    clock_now = _fixed_now()

    async def generate_fn(plan):
        generated.append(plan.issue_key)
        # 真实流程会在成功后 upsert 期刊；测试模拟同一条去重来源
        await _issues_store().upsert_issue(
            config_id=1,
            issue_key=plan.issue_key,
            title="t",
            body_html="",
            sections_json="[]",
            refs_json="{}",
            model="m",
            published_at="2026-09-18T08:00:00+00:00",
        )
        return {"issue_key": plan.issue_key}

    issues = _issues_store()
    config = run(_config_store().get_config(1))
    scheduler = GptDigestScheduler(store._db, clock=lambda _tz: clock_now)
    first = run(scheduler.maybe_generate_config(generate_fn, config, issues))
    assert first == {"issue_key": "2026-09-18"}
    # 重启（新 scheduler 实例）+ 同一天 → 期刊已存在，幂等不重跑
    scheduler2 = GptDigestScheduler(store._db, clock=lambda _tz: clock_now)
    config = run(_config_store().get_config(1))
    assert run(scheduler2.maybe_generate_config(generate_fn, config, issues)) is None
    assert generated == ["2026-09-18"]
    # 错过 08:00、09:30 重启：单时点配置按 hour 相等门控，不再触发
    later = _fixed_now() + timedelta(hours=2)
    scheduler3 = GptDigestScheduler(store._db, clock=lambda _tz: later)
    assert run(scheduler3.maybe_generate_config(generate_fn, config, issues)) is None


def test_f02_slots_plan_boundaries_and_dedup(client):
    """F02：早晚两刊窗口按相邻时点切分（不重叠不漏）；错过补刊窗口
    跳过；显式修订取最近已过期时点。"""
    from lumirss.gpt_digest import plan_run

    config = {
        "id": 2,
        "name": "早晚刊",
        "enabled": True,
        "hour": 8,
        "timezone": "UTC",
        "windowHours": 24,
        "limitCount": 10,
        "perSourceCap": 0,
        "feedUrlAllow": "",
        "slots": [8, 20],
    }
    # 08:30 → 早刊窗口 = [昨 20:00, 今 08:00)，边界统一 UTC Z 形态
    now = datetime(2026, 9, 18, 8, 30, 0, tzinfo=UTC)
    plan = plan_run(config, now)
    assert plan.issue_key == "2026-09-18-08"
    assert plan.window_end == "2026-09-18T08:00:00Z"
    assert plan.window_start == "2026-09-17T20:00:00Z"
    # 12:00 → 早刊补刊窗口（65 分钟）已过、晚刊未到 → 不运行
    assert plan_run(config, datetime(2026, 9, 18, 12, 0, tzinfo=UTC)) is None
    # 09:00 → 早刊补刊窗口内（60 分钟 ≤ 65）仍可运行
    assert plan_run(config, datetime(2026, 9, 18, 9, 0, tzinfo=UTC)) is not None
    # 20:30 → 晚刊窗口 = [08:00, 20:00)，与早刊不重叠不漏项
    evening = plan_run(config, datetime(2026, 9, 18, 20, 30, tzinfo=UTC))
    assert evening.issue_key == "2026-09-18-20"
    assert evening.window_start == "2026-09-18T08:00:00Z"
    assert evening.window_end == "2026-09-18T20:00:00Z"
    # 显式修订路径（catchup 不限）：任意时刻取最近已过期时点
    revision = plan_run(config, datetime(2026, 9, 18, 23, 0, tzinfo=UTC), catchup_minutes=None)
    assert revision.issue_key == "2026-09-18-20"


def test_f02_slot_scheduler_skips_existing_issue(client):
    """F02 去重：期刊 (config_id, issue_key) 已存在 → 调度跳过，
    绝不重写已发布期（重启/错过时刻均收敛到同一规则）。"""
    store = _store()
    issues = _issues_store()
    run(
        issues.upsert_issue(
            config_id=1,
            issue_key="2026-09-18",
            title="已有早刊",
            body_html="<p>x</p>",
            sections_json="[]",
            refs_json="{}",
            model="m",
            published_at="2026-09-18T00:00:00+00:00",
        )
    )
    clock_now = _fixed_now()

    async def generate_fn(plan):
        raise AssertionError("不应重跑已存在的期号")

    config = run(_config_store().get_config(1))
    scheduler = GptDigestScheduler(store._db, clock=lambda _tz: clock_now)
    assert run(scheduler.maybe_generate_config(generate_fn, config, issues)) is None


def test_f08_revise_issue_endpoint(client):
    """F08：人工修订同一期（entry id/首发时刻不变）；幽灵引用 422；
    不存在的期号 404。"""
    issues = _issues_store()
    run(
        issues.upsert_issue(
            config_id=1,
            issue_key="2026-09-18",
            title="原标题",
            body_html="<p>原</p>",
            sections_json='[{"heading":"h","items":[{"summary":"s","sourceIds":["s1"]}]}]',
            refs_json='{"s1": {"title": "T", "url": "https://a.example.com/x", "feedTitle": "F", "publishedAt": "2026-09-18T00:00:00+00:00"}}',
            model="m",
            published_at="2026-09-18T00:00:00+00:00",
        )
    )
    ok = client.put(
        "/api/v1/gpt-digest/configs/1/issues/2026-09-18",
        json={
            "title": "人工修订版",
            "sections": [
                {"heading": "主题", "items": [{"summary": "改后的总结。", "sourceIds": ["s1"], "uncertainty": None}]}
            ],
        },
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()["issue"]
    assert body["title"] == "人工修订版"
    assert body["sections"][0]["items"][0]["summary"] == "改后的总结。"

    bad = client.put(
        "/api/v1/gpt-digest/configs/1/issues/2026-09-18",
        json={
            "title": "x",
            "sections": [{"heading": "h", "items": [{"summary": "s", "sourceIds": ["ghost"]}]}],
        },
    )
    assert bad.status_code == 422
    assert client.put(
        "/api/v1/gpt-digest/configs/1/issues/1999-01-01",
        json={"title": "x", "sections": []},
    ).status_code == 404


def test_f05_explain_issue_creates_variant(client):
    """F05：解释版是独立条目（key += -x），引用沿用原版；原版不变。"""
    issues = _issues_store()
    run(
        issues.upsert_issue(
            config_id=1,
            issue_key="2026-09-18",
            title="原版",
            body_html="<p>原</p>",
            sections_json='[{"heading":"主题","items":[{"summary":"术语甲的总结。","sourceIds":["s1"],"uncertainty":null}]}]',
            refs_json='{"s1": {"title": "T", "url": "https://a.example.com/x", "feedTitle": "F", "publishedAt": "2026-09-18T00:00:00+00:00"}}',
            model="m",
            published_at="2026-09-18T00:00:00+00:00",
        )
    )
    provider = _FakeProvider(
        '{"title":"初学者版","sections":[{"heading":"主题","items":[{"summary":"解释后的总结。","sourceIds":["s1"],"uncertainty":"术语甲指代不明"}]}],"limitations":[]}'
    )
    config = run(_config_store().get_config(1))
    row = run(
        explain_issue(
            _config_store(),
            issues,
            config=config,
            ai_settings=_FakeAiSettings(),
            provider_factory=_ok(provider),
            issue_key="2026-09-18",
        )
    )
    assert row["issue_key"] == "2026-09-18-x"
    assert row["title"].startswith("〔解释版〕")
    # 原版不受影响
    assert run(issues.get_issue(1, "2026-09-18"))["title"] == "原版"
    # 幽灵引用被拒
    bad = _FakeProvider('{"title":"x","sections":[{"heading":"h","items":[{"summary":"s","sourceIds":["ghost"]}]}],"limitations":[]}')
    with pytest.raises(DigestOutputInvalid):
        run(
            explain_issue(
                _config_store(),
                issues,
                config=config,
                ai_settings=_FakeAiSettings(),
                provider_factory=_ok(bad),
                issue_key="2026-09-18",
            )
        )


def test_f03_weekly_aggregates_recent_issues(client):
    """F03：周报聚合最近 7 天日刊（含引用回溯）；空输入拒绝。"""
    issues = _issues_store()
    run(
        issues.upsert_issue(
            config_id=1,
            issue_key="2026-09-16",
            title="周一刊",
            body_html="<p>a</p>",
            sections_json='[{"heading":"h","items":[{"summary":"进展A。","sourceIds":["s1"],"uncertainty":null}]}]',
            refs_json='{"s1": {"title": "A", "url": "https://x.example.com/a", "feedTitle": "F1", "publishedAt": "2026-09-16T00:00:00+00:00"}}',
            model="m",
            published_at="2026-09-16T00:00:00+00:00",
        )
    )
    run(
        issues.upsert_issue(
            config_id=1,
            issue_key="2026-09-17",
            title="周二刊",
            body_html="<p>b</p>",
            sections_json='[{"heading":"h","items":[{"summary":"进展B。","sourceIds":["s1"],"uncertainty":null}]}]',
            refs_json='{"s1": {"title": "B", "url": "https://x.example.com/b", "feedTitle": "F1", "publishedAt": "2026-09-17T00:00:00+00:00"}}',
            model="m",
            published_at="2026-09-17T00:00:00+00:00",
        )
    )
    provider = _FakeProvider(
        '{"title":"一周回顾","sections":[{"heading":"演进","items":[{"summary":"A 之后出现 B。","sourceIds":["w1:s1","w2:s1"],"uncertainty":null}]}],"limitations":[]}'
    )
    config = run(_config_store().get_config(1))
    row = run(
        generate_weekly(
            _config_store(),
            issues,
            config=config,
            ai_settings=_FakeAiSettings(),
            provider_factory=_ok(provider),
            now=_fixed_now(),
        )
    )
    assert row["issue_key"].startswith("2026-W")
    refs = json.loads(row["refs_json"])
    assert refs["w1:s1"]["issueKey"] == "2026-09-16"
    assert refs["w2:s1"]["issueKey"] == "2026-09-17"
    assert row["body_html"].count("https://x.example.com/") == 2

    # 空输入：新建配置无日刊 → 422 no_material
    empty = run(_config_store().create_config({"name": "空周报", "timezone": "UTC"}))
    route = client.post(f"/api/v1/gpt-digest/configs/{empty['id']}/weekly")
    assert route.status_code == 422
    assert route.json()["error"]["type"] == "no_material"


def test_f07_compare_with_previous(client):
    """F07：对照上一期；引用可追溯（prev:/cur: 复合编号）；无上一期 422。"""
    issues = _issues_store()
    run(
        issues.upsert_issue(
            config_id=1,
            issue_key="2026-09-16",
            title="上一期",
            body_html="<p>a</p>",
            sections_json='[{"heading":"h","items":[{"summary":"事项A。","sourceIds":["s1"],"uncertainty":null}]}]',
            refs_json='{"s1": {"title": "A", "url": "https://x.example.com/a", "feedTitle": "F", "publishedAt": "2026-09-16T00:00:00+00:00"}}',
            model="m",
            published_at="2026-09-16T00:00:00+00:00",
        )
    )
    run(
        issues.upsert_issue(
            config_id=1,
            issue_key="2026-09-17",
            title="本期",
            body_html="<p>b</p>",
            sections_json='[{"heading":"h","items":[{"summary":"事项A有新进展。","sourceIds":["s2"],"uncertainty":null}]}]',
            refs_json='{"s2": {"title": "B", "url": "https://x.example.com/b", "feedTitle": "F", "publishedAt": "2026-09-17T00:00:00+00:00"}}',
            model="m",
            published_at="2026-09-17T00:00:00+00:00",
        )
    )
    provider = _FakeProvider(
        '{"title":"相邻对照","sections":[{"heading":"变化","items":[{"summary":"[新增] 事项A的新进展。","sourceIds":["prev:s1","cur:s2"],"uncertainty":null}]}],"limitations":[]}'
    )
    config = run(_config_store().get_config(1))
    row = run(
        compare_with_previous(
            _config_store(),
            issues,
            config=config,
            ai_settings=_FakeAiSettings(),
            provider_factory=_ok(provider),
            issue_key="2026-09-17",
        )
    )
    assert row["issue_key"] == "2026-09-17-d"
    assert row["title"].startswith("〔对照〕")
    refs = json.loads(row["refs_json"])
    assert refs["prev:s1"]["issueKey"] == "2026-09-16"
    assert refs["cur:s2"]["issueKey"] == "2026-09-17"
    assert row["body_html"].count("https://x.example.com/") == 2

    # 无上一期 → 422
    route = client.post("/api/v1/gpt-digest/configs/1/issues/2026-09-16/compare")
    assert route.status_code == 422
    assert route.json()["error"]["type"] == "no_previous"


def test_f28_compare_facts_on_demand(client):
    """F28：期内条目对照——按需生成不落库；矛盾并列。"""
    issues = _issues_store()
    run(
        issues.upsert_issue(
            config_id=1,
            issue_key="2026-09-18",
            title="对照期",
            body_html="<p>原</p>",
            sections_json='[{"heading":"h","items":[{"summary":"来源一称 X 已发生。","sourceIds":["s1"],"uncertainty":null},{"summary":"来源二称 X 未发生。","sourceIds":["s2"],"uncertainty":null}]}]',
            refs_json='{"s1": {"title": "A", "url": "https://x.example.com/a", "feedTitle": "F", "publishedAt": "2026-09-18T00:00:00+00:00"}, "s2": {"title": "B", "url": "https://x.example.com/b", "feedTitle": "F", "publishedAt": "2026-09-18T00:00:00+00:00"}}',
            model="m",
            published_at="2026-09-18T00:00:00+00:00",
        )
    )
    provider = _FakeProvider(
        '{"title":"事实对照","sections":[{"heading":"分歧","items":[{"summary":"两来源对 X 的陈述矛盾，并列存疑。","sourceIds":["2026-09-18:s1","2026-09-18:s2"],"uncertainty":"矛盾未裁决"}]}],"limitations":[]}'
    )
    result = run(
        compare_facts(
            issues,
            config_id=1,
            issue_key="2026-09-18",
            ai_settings=_FakeAiSettings(),
            provider_factory=_ok(provider),
        )
    )
    assert result["title"] == "事实对照"
    assert result["bodyHtml"]
    assert len(run(issues.recent_issues(1, 10))) == 1  # 不落库


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
            config_id=1,
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
    assert "urn:lumirss:gptdigest:1:2026-09-18" in ok.text
    etag = ok.headers["ETag"]
    not_modified = client.get(atom_path, headers={"If-None-Match": etag})
    assert not_modified.status_code == 304

    # token 错误 → 404；列表接口不带正文
    assert client.get("/feeds/gpt-digest/wrong-token.atom").status_code == 404
    listing = client.get("/api/v1/gpt-digest/issues").json()
    assert listing["items"][0]["title"] == "订阅可见的一期"
