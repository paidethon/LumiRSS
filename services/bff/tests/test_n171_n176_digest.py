"""N171–N176 —— NR1 日报增强域。

N171 编辑计划（发布日集合 + 周末独立时点 + DST 只生成一次）；
N172 多模型路由（分阶段模型、草稿保留、重试润色、阶段命名错误）；
N173 事实检查视图（句子映射、逐句修订、Atom 同步、待核实标注）；
N174 栏目结构（固定栏目、空栏目策略、数量上限诚实截断）；
N175 阅读时长控制（trim 到预算、素材篮、预览前后对比）；
N176 引用去重（同事件聚合、跨日不合并、数字分歧标注）。
全部走本地假 provider，不触网；调度判定用注入的固定时钟。
"""

import asyncio
import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from lumirss.ai_provider import AiTimeout
from lumirss.gpt_digest import (
    DigestPolishFailed,
    GptDigestScheduler,
    generate_issue,
    plan_run,
    retry_polish_issue,
)
from lumirss.gpt_digest_configs import GptDigestConfigStore, parse_days
from lumirss.gpt_digest_issues import GptDigestIssuesStore
from lumirss.main import app


def run(coroutine):
    return asyncio.run(coroutine)


def _config_store():
    return GptDigestConfigStore(app.state.db)


def _issues_store():
    return GptDigestIssuesStore(app.state.db)


def _doc(item_id: str, published: str, title: str | None = None, content: str | None = None) -> dict:
    return {
        "item_id": item_id,
        "entryRef": item_id,
        "feedUrl": "https://tech.example.com/rss",
        "feedTitle": "示例源",
        "title": title or f"文章 {item_id}",
        "url": f"https://tech.example.com/{item_id}",
        "publishedAt": published,
        "read": False,
        "starred": False,
        "contentText": content or f"{item_id} 的正文内容。",
    }


def _fixed_now() -> datetime:
    return datetime(2026, 9, 18, 8, 5, 0, tzinfo=UTC)  # 周五


_DEFAULT_CONFIG = {
    "id": 1,
    "name": "默认日报",
    "enabled": True,
    "hour": 8,
    "timezone": "UTC",
    "windowHours": 24,
    "limitCount": 10,
    "perSourceCap": 0,
    "feedUrlAllow": "",
    "sourceKind": "window",
    "lookbackDays": 7,
    "slots": [],
    "days": [],
    "weekendHours": [],
    "stageModels": {},
    "columns": [],
    "targetReadingMinutes": 0,
    "clusterEnabled": False,
}


def _config(**over) -> dict:
    base = dict(_DEFAULT_CONFIG)
    base.update(over)
    return base


class _FakeAiSettings:
    async def load(self):
        return {"ai.base_url": "https://ai.local", "ai.model": "base-model"}


class _FakeAdapter:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    class _Page:
        def __init__(self, docs):
            self.documents = docs

    async def list_entry_documents(self, limit: int = 120):
        return _FakeAdapter._Page(self._docs)


def _ok_factory(provider, record=None):
    async def factory(base_url: str, model: str, explicit_model: bool = False):
        if record is not None:
            record.append((base_url, model, explicit_model))
        return provider

    return factory


class _StagedProvider:
    """按 system 提示里的阶段标记返回对应输出；fail_stage 时抛错。"""

    def __init__(
        self,
        select_raw: str,
        summarize_raw: str,
        polish_raw: str | None = None,
        fail_stage: str | None = None,
    ):
        self.select_raw = select_raw
        self.summarize_raw = summarize_raw
        self.polish_raw = polish_raw
        self.fail_stage = fail_stage
        self.calls: list[str] = []
        self.systems: list[str] = []
        self.users: list[str] = []

    async def complete(self, *, messages):
        system = messages[0]["content"]
        user = messages[1]["content"]
        if "（select）" in system:
            self.calls.append("select")
            self.systems.append(system)
            self.users.append(user)
            if self.fail_stage == "select":
                raise AiTimeout("上游超时")
            return self.select_raw
        if "（summarize）" in system:
            self.calls.append("summarize")
            self.systems.append(system)
            self.users.append(user)
            if self.fail_stage == "summarize":
                raise AiTimeout("上游超时")
            return self.summarize_raw
        if "（polish）" in system:
            self.calls.append("polish")
            self.systems.append(system)
            self.users.append(user)
            if self.fail_stage == "polish":
                raise AiTimeout("上游超时")
            assert self.polish_raw is not None
            return self.polish_raw
        raise AssertionError(f"未知阶段提示：{system[:60]}")


def _select_raw(groups: list[list[str]]) -> str:
    return json.dumps(
        {
            "title": "测试日报",
            "assignments": [
                {"heading": f"栏目{i + 1}", "sourceIds": group}
                for i, group in enumerate(groups)
            ],
        },
        ensure_ascii=False,
    )


def _summarize_raw(items: list[dict], title: str = "测试日报") -> str:
    return json.dumps(
        {
            "title": title,
            "sections": [{"heading": s["heading"], "items": s["items"]} for s in items],
            "limitations": [],
        },
        ensure_ascii=False,
    )


def _item(summary: str, sids: list[str]) -> dict:
    return {"summary": summary, "sourceIds": sids, "uncertainty": None}


def _single_raw(items: list[dict], heading: str = "主题", title: str = "测试日报") -> str:
    return _summarize_raw([{"heading": heading, "items": items}], title=title)


# ---- N171 编辑计划 -----------------------------------------------------------


def test_n171_parse_days_accepts_shapes_and_bounds():
    assert parse_days([]) == []
    assert parse_days("[1,3,5]") == [1, 3, 5]
    assert parse_days([6, "2", 2, 9, -1]) == [2, 6]
    assert parse_days("1,3") == [1, 3]
    assert parse_days("nope") == []


def test_n171_weekend_only_config_skips_tuesday():
    """验收：仅周末发布的配置在周二不运行；周六/周日按计划运行。"""
    config = _config(days=[5, 6])
    tuesday = datetime(2026, 9, 15, 8, 30, 0, tzinfo=UTC)  # 周二
    assert tuesday.weekday() == 1
    assert plan_run(config, tuesday) is None
    saturday = datetime(2026, 9, 19, 8, 30, 0, tzinfo=UTC)
    assert saturday.weekday() == 5
    plan = plan_run(config, saturday)
    assert plan is not None and plan.issue_key == "2026-09-19"
    # 空集合 = 每天发布（历史行为）
    assert plan_run(_config(days=[]), tuesday) is not None


def test_n171_weekend_hours_replace_weekday_plan():
    """周末独立时点：周六用 weekendHours（10 点），平日仍用 hour=8。"""
    config = _config(hour=8, weekendHours=[10])
    saturday_1030 = datetime(2026, 9, 19, 10, 30, 0, tzinfo=UTC)
    plan = plan_run(config, saturday_1030)
    assert plan is not None and plan.issue_key == "2026-09-19-10"
    # 周六 08:30 未到周末时点 10 点 → 不运行
    assert plan_run(config, datetime(2026, 9, 19, 8, 30, 0, tzinfo=UTC)) is None
    # 周五 08:30 仍走平日 hour=8
    friday = plan_run(config, _fixed_now())
    assert friday is not None and friday.issue_key == "2026-09-18"


def test_n171_dst_transition_generates_once_with_fixed_clock(client):
    """验收：DST 切换日（美东 2026-11-01 回拨）墙钟 01:00 出现两次，
    同一期号只生成一次；第二次调度命中已有期号跳过。"""
    store_config = run(
        _config_store().update_config(
            1,
            {
                "enabled": True,
                "hour": 8,
                "timezone": "America/New_York",
                "slots": [1],
            },
        )
    )
    ny = ZoneInfo("America/New_York")
    first_one_oclock = datetime(2026, 11, 1, 1, 0, 0, tzinfo=ny)  # EDT（fold=0）
    second_one_oclock = datetime(2026, 11, 1, 1, 0, 0, tzinfo=ny, fold=1)  # EST
    assert (
        second_one_oclock.astimezone(UTC) - first_one_oclock.astimezone(UTC)
    ).total_seconds() == 3600
    generated: list[str] = []

    async def generate_fn(plan):
        generated.append(plan.issue_key)
        await _issues_store().upsert_issue(
            config_id=1,
            issue_key=plan.issue_key,
            title="dst",
            body_html="",
            sections_json="[]",
            refs_json="{}",
            model="m",
            published_at="2026-11-01T06:00:00+00:00",
        )
        return {"issue_key": plan.issue_key}

    issues = _issues_store()
    scheduler = GptDigestScheduler(
        app.state.db, clock=lambda _tz: first_one_oclock
    )
    first = run(scheduler.maybe_generate_config(generate_fn, store_config, issues))
    assert first == {"issue_key": "2026-11-01-01"}
    # 回拨后的第二次墙钟 01:00（EST）：期号相同 → 已存在 → 不再生成
    scheduler2 = GptDigestScheduler(
        app.state.db, clock=lambda _tz: second_one_oclock
    )
    assert (
        run(scheduler2.maybe_generate_config(generate_fn, store_config, issues))
        is None
    )
    assert generated == ["2026-11-01-01"]
    assert len(run(issues.recent_issues(1, 10))) == 1


def test_n171_config_roundtrip_days_and_weekend_hours(client):
    config = run(
        _config_store().update_config(1, {"days": [0, 6], "weekendHours": [9, 21]})
    )
    assert config["days"] == [0, 6]
    assert config["weekendHours"] == [9, 21]
    # 非法值收敛：越界日 / 越界小时被丢弃
    config = run(
        _config_store().update_config(1, {"days": [9, -1, 3], "weekendHours": [99, 5]})
    )
    assert config["days"] == [3]
    assert config["weekendHours"] == [5]
    # 清空 = 回到每天 + 沿用平日计划
    config = run(_config_store().update_config(1, {"days": [], "weekendHours": []}))
    assert config["days"] == [] and config["weekendHours"] == []


# ---- N172 多模型路由 ---------------------------------------------------------


def _polished_raw(sections: list[dict], title: str = "润色后的标题") -> str:
    return json.dumps(
        {"title": title, "sections": sections, "limitations": []},
        ensure_ascii=False,
    )


def _summarize_sections(heading: str = "要点", summary: str = "这是总结。") -> list[dict]:
    return [{"heading": heading, "items": [_item(summary, ["s1"])]}]


async def _generate(config, provider, record=None, draft=True, docs=None):
    if docs is None:
        docs = [_doc("a", "2026-09-18T00:10:00+00:00")]
    adapter = _FakeAdapter(docs)
    return await generate_issue(
        _config_store(),
        _issues_store(),
        config=config,
        adapter=adapter,
        ai_settings=_FakeAiSettings(),
        provider_factory=_ok_factory(provider, record),
        db=app.state.db,
        now=_fixed_now(),
        draft=draft,
    )


def test_n172_stage_models_used_per_stage(client):
    """验收：每个阶段用配置的阶段模型调用（fake factory 逐次记录）。"""
    provider = _StagedProvider(
        _select_raw([["s1"]]),
        _summarize_raw(_summarize_sections()),
        _polished_raw([{"heading": "要点", "items": [_item("润色后的总结。", ["s1"])]}]),
    )
    record: list[tuple] = []
    config = _config(
        stageModels={"select": "m-sel", "summarize": "m-sum", "polish": "m-pol"}
    )
    row = run(_generate(config, provider, record))
    assert [model for _url, model, _exp in record] == ["m-sel", "m-sum", "m-pol"]
    assert provider.calls == ["select", "summarize", "polish"]
    assert all(exp for _url, _model, exp in record)  # 显式阶段路由
    meta = json.loads(row["meta_json"])
    assert meta["stageModels"] == {
        "select": "m-sel",
        "summarize": "m-sum",
        "polish": "m-pol",
    }
    assert "polishFailed" not in meta
    # 显式草稿路径：润色后的输出落库
    assert json.loads(row["sections_json"])["title"] == "润色后的标题"


def test_n172_partial_stage_models_fall_back_to_base(client):
    """未配置的阶段回退基础模型（非显式路由——P17 profile 语义保留）。"""
    provider = _StagedProvider(
        _select_raw([["s1"]]),
        _summarize_raw(_summarize_sections()),
        _polished_raw(_summarize_sections()),
    )
    record: list[tuple] = []
    config = _config(stageModels={"polish": "m-pol"})
    run(_generate(config, provider, record))
    assert [(model, exp) for _url, model, exp in record] == [
        ("base-model", False),
        ("base-model", False),
        ("m-pol", True),
    ]


def test_n172_no_stage_models_single_call_unchanged(client):
    """未配置分阶段模型 = 单次调用（历史行为）；meta 为空对象。"""

    class _SingleProvider:
        def __init__(self, raw):
            self.raw = raw
            self.calls = 0

        async def complete(self, *, messages):
            self.calls += 1
            assert "阶段" not in messages[0]["content"]
            return self.raw

    single = _SingleProvider(_single_raw([_item("总结。", ["s1"])]))
    record: list[tuple] = []
    row = run(_generate(_config(), single, record))
    assert single.calls == 1
    assert record == [("https://ai.local", "base-model", False)]
    # meta 只含 N173 句子映射（无分阶段/润色等运行时标注）
    assert json.loads(row["meta_json"]) == {
        "sentenceMap": [{"sentence": "总结。", "refs": ["s1"], "verified": True}]
    }


def test_n172_polish_failure_keeps_draft_and_retry_polish(client):
    """验收：润色失败 → 选材+总结草稿保留（polishFailed 如实标注），
    retry-polish 仅补润色成功。"""
    provider = _StagedProvider(
        _select_raw([["s1"]]),
        _summarize_raw(_summarize_sections(summary="选材总结成果。"), title="草稿标题"),
        fail_stage="polish",
    )
    config = _config(
        stageModels={"select": "m-sel", "summarize": "m-sum", "polish": "m-pol"}
    )
    issues = _issues_store()
    with pytest.raises(DigestPolishFailed) as excinfo:
        run(_generate(config, provider))
    assert "润色阶段（polish）" in str(excinfo.value)
    row = run(issues.get_issue(1, "2026-09-18"))
    assert row is not None and row["status"] == "draft"
    stored = json.loads(row["sections_json"])
    assert stored["title"] == "草稿标题"  # 选材+总结成果保留
    meta = json.loads(row["meta_json"])
    assert meta["polishFailed"] is True
    last_error = run(_config_store().get_config(1))["lastError"] or ""
    assert "润色阶段（polish）" in last_error

    # retry-polish：仅润色——好的 provider 只被 ask polish
    good = _StagedProvider(
        _select_raw([["s1"]]),
        _summarize_raw(_summarize_sections()),
        _polished_raw([{"heading": "要点", "items": [_item("重试润色后的总结。", ["s1"])]}]),
    )
    fixed = run(
        retry_polish_issue(
            issues,
            _config_store(),
            config_id=1,
            issue_key="2026-09-18",
            config=config,
            ai_settings=_FakeAiSettings(),
            provider_factory=_ok_factory(good),
        )
    )
    assert good.calls == ["polish"]  # 只补润色，不重跑选材/总结
    assert fixed["status"] == "draft"  # 状态不变
    assert json.loads(fixed["sections_json"])["title"] == "润色后的标题"
    meta = json.loads(fixed["meta_json"])
    assert "polishFailed" not in meta
    assert meta["stageModels"]["polish"] == "m-pol"
    assert meta["polishedAt"]
    assert fixed["model"] == "m-pol"


def test_n172_select_failure_aborts_cleanly(client):
    """验收：选材失败 → 带阶段名的干净中止，不产生任何期号。"""
    provider = _StagedProvider(
        _select_raw([["s1"]]),
        _summarize_raw(_summarize_sections()),
        fail_stage="select",
    )
    config = _config(stageModels={"select": "m-sel"})
    with pytest.raises(AiTimeout) as excinfo:
        run(_generate(config, provider))
    assert "选材阶段（select）" in str(excinfo.value)
    assert provider.calls == ["select"]  # 失败后不再调用后续阶段
    assert run(_issues_store().recent_issues(1, 10)) == []
    last_error = run(_config_store().get_config(1))["lastError"] or ""
    assert "选材阶段（select）" in last_error


def test_n172_summarize_failure_names_stage(client):
    """总结失败同样带阶段名，且不落任何期号。"""
    provider = _StagedProvider(
        _select_raw([["s1"]]),
        _summarize_raw(_summarize_sections()),
        fail_stage="summarize",
    )
    config = _config(stageModels={"summarize": "m-sum"})
    with pytest.raises(AiTimeout) as excinfo:
        run(_generate(config, provider))
    assert "总结阶段（summarize）" in str(excinfo.value)
    assert run(_issues_store().recent_issues(1, 10)) == []


def test_n172_retry_polish_endpoint(client, monkeypatch):
    """路由面：retry-polish 成功 200；期号不存在 422 no_material。"""
    issues = _issues_store()
    run(
        issues.upsert_issue(
            config_id=1,
            issue_key="2026-09-18",
            title="草稿",
            body_html="<p>x</p>",
            sections_json=json.dumps(
                {
                    "title": "草稿",
                    "sections": [{"heading": "要点", "items": [_item("原文。", ["s1"])]}],
                    "limitations": [],
                },
                ensure_ascii=False,
            ),
            refs_json='{"s1": {"title": "T", "url": "https://a.example.com/x", "feedTitle": "F", "publishedAt": "2026-09-18T00:00:00+00:00"}}',
            model="m",
            published_at="2026-09-18T00:00:00+00:00",
            status_for_new="draft",
            meta_json=json.dumps({"polishFailed": True}, ensure_ascii=False),
        )
    )
    good = _StagedProvider(
        _select_raw([["s1"]]),
        _summarize_raw(_summarize_sections()),
        _polished_raw([{"heading": "要点", "items": [_item("润色文。", ["s1"])]}]),
    )

    def _fake_ai_deps(_state):
        return _FakeAiSettings(), _ok_factory(good)

    monkeypatch.setattr("lumirss.gpt_digest._build_ai_deps", _fake_ai_deps)
    ok = client.post("/api/v1/gpt-digest/configs/1/issues/2026-09-18/retry-polish")
    assert ok.status_code == 200, ok.text
    body = ok.json()["issue"]
    assert body["meta"]["stageModels"]["polish"] == "base-model"
    assert "polishFailed" not in body["meta"]

    missing = client.post("/api/v1/gpt-digest/configs/1/issues/1999-01-01/retry-polish")
    assert missing.status_code == 422
    assert missing.json()["error"]["type"] == "no_material"


def test_n172_stage_models_config_roundtrip_and_bounds(client):
    config = run(
        _config_store().update_config(
            1, {"stageModels": {"select": " sel-model ", "bogus": "x", "polish": ""}}
        )
    )
    assert config["stageModels"] == {"select": "sel-model"}
    config = run(_config_store().update_config(1, {"stageModels": {}}))
    assert config["stageModels"] == {}
    config = run(_config_store().update_config(1, {"stageModels": "not-json"}))
    assert config["stageModels"] == {}


# ---- N173 事实检查视图 -------------------------------------------------------


class _RawProvider:
    def __init__(self, raw: str):
        self.raw = raw
        self.calls = 0

    async def complete(self, *, messages):
        self.calls += 1
        return self.raw


def test_n173_sentence_map_built_from_generation(client):
    """验收：生成后 issue 载荷携带逐句映射（句子继承条目引用）。"""
    provider = _RawProvider(
        _single_raw([_item("第一句关于来源。第二句补充背景！", ["s1"])])
    )
    row = run(_generate(_config(), provider))
    dto = _issues_store().issue_to_dto(row)
    assert [
        {"sentence": s["sentence"], "refs": s["refs"], "verified": s["verified"]}
        for s in dto["sentenceMap"]
    ] == [
        {"sentence": "第一句关于来源。", "refs": ["s1"], "verified": True},
        {"sentence": "第二句补充背景！", "refs": ["s1"], "verified": True},
    ]
    # 切分保真：句子重组 == 原文
    assert "".join(s["sentence"] for s in dto["sentenceMap"]) == "第一句关于来源。第二句补充背景！"


def test_n173_full_revise_marks_changed_sentences_unmapped(client):
    """全量修订：改写的句子匹配不到引用 → 待核实；未动句子保留引用。"""
    run(
        _issues_store().upsert_issue(
            config_id=1,
            issue_key="2026-09-18",
            title="原标题",
            body_html="<p>原</p>",
            sections_json='[{"heading":"h","items":[{"summary":"甲句内容。乙句内容。","sourceIds":["s1"]}]}]',
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
                {"heading": "h", "items": [{"summary": "甲句内容。人工改写的句子。", "sourceIds": ["s1"]}]}
            ],
        },
    )
    assert ok.status_code == 200, ok.text
    dto = ok.json()["issue"]
    mapped = {s["sentence"]: s for s in dto["sentenceMap"]}
    assert mapped["甲句内容。"]["verified"] is True
    assert mapped["人工改写的句子。"]["verified"] is False  # 待核实
    assert mapped["人工改写的句子。"]["refs"] == []


def test_n173_per_sentence_ops_persist_and_atom_follows(client):
    """验收：逐句改写保留并重算映射；删除的句子从 Atom 导出消失。"""
    run(
        _issues_store().upsert_issue(
            config_id=1,
            issue_key="2026-09-18",
            title="Atom 同步期",
            body_html="<p>原</p>",
            sections_json='[{"heading":"h","items":[{"summary":"甲句内容。乙句内容。丙句内容。","sourceIds":["s1"]}]}]',
            refs_json='{"s1": {"title": "T", "url": "https://a.example.com/x", "feedTitle": "示例源", "publishedAt": "2026-09-18T00:00:00+00:00"}}',
            model="m",
            published_at="2026-09-18T00:00:00+00:00",
        )
    )
    revised = client.put(
        "/api/v1/gpt-digest/configs/1/issues/2026-09-18",
        json={
            "sentenceOps": [
                {"op": "revise", "sectionIndex": 0, "itemIndex": 0, "sentenceIndex": 1, "text": "乙句人工改写。"}
            ]
        },
    )
    assert revised.status_code == 200, revised.text
    dto = revised.json()["issue"]
    item = dto["sections"][0]["items"][0]
    assert item["summary"] == "甲句内容。乙句人工改写。丙句内容。"
    mapped = {s["sentence"]: s for s in dto["sentenceMap"]}
    assert mapped["乙句人工改写。"]["verified"] is False
    assert mapped["甲句内容。"]["verified"] is True

    # 删除一句 → 内容与 Atom 都不再包含
    deleted = client.put(
        "/api/v1/gpt-digest/configs/1/issues/2026-09-18",
        json={
            "sentenceOps": [
                {"op": "delete", "sectionIndex": 0, "itemIndex": 0, "sentenceIndex": 2}
            ]
        },
    )
    assert deleted.status_code == 200
    dto = deleted.json()["issue"]
    assert dto["sections"][0]["items"][0]["summary"] == "甲句内容。乙句人工改写。"
    assert all(s["sentence"] != "丙句内容。" for s in dto["sentenceMap"])

    # Atom 导出与内容同步（body_html 已重渲染）
    atom_path = client.get("/api/v1/gpt-digest/feed").json()["atomPath"]
    assert atom_path.startswith("/feeds/gpt-digest/")
    token = atom_path.split("/")[-1][: -len(".atom")]
    atom = client.get(f"/feeds/gpt-digest/{token}.atom")
    assert atom.status_code == 200
    assert "丙句内容。" not in atom.text
    assert "甲句内容。" in atom.text

    # 非法操作：越界索引 422；revise 缺文本 422
    bad_index = client.put(
        "/api/v1/gpt-digest/configs/1/issues/2026-09-18",
        json={"sentenceOps": [{"op": "delete", "sectionIndex": 0, "itemIndex": 0, "sentenceIndex": 9}]},
    )
    assert bad_index.status_code == 422
    bad_text = client.put(
        "/api/v1/gpt-digest/configs/1/issues/2026-09-18",
        json={"sentenceOps": [{"op": "revise", "sectionIndex": 0, "itemIndex": 0, "sentenceIndex": 0, "text": "  "}]},
    )
    assert bad_text.status_code == 422


def test_n173_split_sentences_roundtrip_and_edges():
    from lumirss.gpt_digest_issues import split_sentences

    text = "A。B！C？\nD…E"
    assert split_sentences(text) == ["A。", "B！", "C？", "\nD…", "E"]
    assert "".join(split_sentences(text)) == text
    assert split_sentences("") == []
    assert split_sentences("没有结束符的句子") == ["没有结束符的句子"]


# ---- N174 栏目结构 -----------------------------------------------------------


def test_n174_three_column_config_sections_exact_and_cap(client):
    """验收：3 栏配置 → sections 恰为配置栏目（按配置顺序）；未知栏目
    丢弃并如实计数；超上限条目诚实截断（meta note）。"""
    provider = _RawProvider(
        json.dumps(
            {
                "title": "栏目测试",
                "sections": [
                    {
                        "heading": "人工智能",
                        "items": [
                            _item("AI 一。", ["s1"]),
                            _item("AI 二。", ["s1"]),
                            _item("AI 三（超限）。", ["s1"]),
                        ],
                    },
                    {"heading": "硬件", "items": [_item("硬件一条。", ["s1"])]},
                    {"heading": "乱入栏目", "items": [_item("不该出现。", ["s1"])]},
                    {"heading": "开源", "items": [_item("开源一条。", ["s1"])]},
                ],
                "limitations": [],
            },
            ensure_ascii=False,
        )
    )
    config = _config(
        columns=[
            {"name": "开源", "count": 3, "emptyPolicy": "hide"},
            {"name": "人工智能", "count": 2, "emptyPolicy": "placeholder"},
            {"name": "硬件", "count": 3, "emptyPolicy": "hide"},
        ]
    )
    row = run(_generate(config, provider))
    stored = json.loads(row["sections_json"])
    assert [s["heading"] for s in stored["sections"]] == ["开源", "人工智能", "硬件"]
    ai_items = stored["sections"][1]["items"]
    assert len(ai_items) == 2  # count 上限
    assert all(item["summary"] != "AI 三（超限）。" for item in ai_items)
    meta = json.loads(row["meta_json"])
    notes = {n["column"]: n for n in meta["columnNotes"]}
    assert notes["人工智能"]["dropped"] == 1 and notes["人工智能"]["reason"] == "count_cap"
    assert notes["乱入栏目"]["dropped"] == 1 and notes["乱入栏目"]["reason"] == "unknown_column"
    # Atom 渲染跟随栏目顺序
    assert row["body_html"].find("开源一条。") < row["body_html"].find("AI 一。")


def test_n174_empty_column_hide_and_placeholder(client):
    """验收：空栏目按 emptyPolicy——hide 整栏消失；placeholder 出现
    「本栏目今日无内容」占位（绝不编造内容）。"""
    provider = _RawProvider(
        _single_raw([_item("只有人工智能有内容。", ["s1"])], heading="人工智能")
    )
    config = _config(
        columns=[
            {"name": "人工智能", "count": 3, "emptyPolicy": "hide"},
            {"name": "硬件", "count": 3, "emptyPolicy": "hide"},
            {"name": "开源", "count": 3, "emptyPolicy": "placeholder"},
        ]
    )
    row = run(_generate(config, provider))
    stored = json.loads(row["sections_json"])
    headings = [s["heading"] for s in stored["sections"]]
    assert headings == ["人工智能", "开源"]  # 硬件（hide）被省略
    placeholder_items = stored["sections"][1]["items"]
    assert placeholder_items[0]["summary"] == "本栏目今日无内容。"
    assert placeholder_items[0]["sourceIds"] == []  # 占位没有伪造引用
    assert "本栏目今日无内容。" in row["body_html"]


def test_n174_no_columns_unchanged(client):
    """未配置栏目 = 历史行为（sections 原样保留）。"""
    provider = _RawProvider(
        _single_raw([_item("内容。", ["s1"])], heading="自由栏目")
    )
    row = run(_generate(_config(), provider))
    stored = json.loads(row["sections_json"])
    assert stored["sections"][0]["heading"] == "自由栏目"
    assert "columnNotes" not in json.loads(row["meta_json"])


# ---- N175 阅读时长控制 -------------------------------------------------------


def _long_summary(seed: str, chars: int) -> str:
    return seed + "字" * (chars - len(seed))


def test_n175_target_trims_to_budget_and_keeps_leftover_pool(client):
    """验收：目标时长把超预算条目移入素材篮（meta.leftoverPool），
    保留条目的引用完整；无目标 = 原样。"""
    long_a = _long_summary("条目A。", 300)
    long_b = _long_summary("条目B。", 500)  # 最长 → 先裁
    long_c = _long_summary("条目C。", 200)
    provider = _RawProvider(
        _single_raw(
            [
                _item(long_a, ["s1"]),
                _item(long_b, ["s2"]),
                _item(long_c, ["s3"]),
            ]
        )
    )
    docs = [
        _doc("a", "2026-09-18T00:10:00+00:00"),
        _doc("b", "2026-09-18T00:20:00+00:00"),
        _doc("c", "2026-09-18T00:30:00+00:00"),
    ]
    config = _config(targetReadingMinutes=1)  # 400 字 ≈ 1 分钟预算
    row = run(_generate(config, provider, docs=docs))
    stored = json.loads(row["sections_json"])
    items = stored["sections"][0]["items"]
    kept_summaries = [i["summary"] for i in items]
    assert _long_summary("条目B。", 500) not in kept_summaries
    kept_chars = sum(len(i["summary"]) for i in items)
    assert kept_chars <= 400  # 收敛到预算内
    meta = json.loads(row["meta_json"])
    assert meta["trim"]["beforeMinutes"] > meta["trim"]["afterMinutes"]
    assert meta["trim"]["targetMinutes"] == 1
    pool = meta["leftoverPool"]
    moved = {entry["summary"] for entry in pool}
    assert _long_summary("条目B。", 500) in moved
    assert _long_summary("条目A。", 300) in moved  # 超预算的第二条也进素材篮
    entry_b = next(e for e in pool if e["summary"].startswith("条目B"))
    assert entry_b["sourceIds"] == ["s2"]
    assert entry_b["refs"][0]["url"] == "https://tech.example.com/b"  # 出处保留
    assert entry_b["refs"][0]["title"] == "文章 b"
    # 保留条目的引用仍出现在正文（选材按时间倒序：条目C 的引用 = s3 → /a）
    assert '<a href="https://tech.example.com/a">示例源</a>' in row["body_html"]

    # 无目标 = 原样（不裁剪、无素材篮）
    provider2 = _RawProvider(
        _single_raw([_item(long_a, ["s1"]), _item(long_b, ["s2"]), _item(long_c, ["s3"])])
    )
    row2 = run(_generate(_config(), provider2, docs=docs))
    assert "leftoverPool" not in json.loads(row2["meta_json"])
    assert len(json.loads(row2["sections_json"])["sections"][0]["items"]) == 3


def test_n175_beyond_column_count_trimmed_first(client):
    """裁剪优先级：超出栏目 count 的条目先于更长条目进素材篮。"""
    short_extra = _long_summary("超配额的短条目。", 100)
    long_normal = _long_summary("配额内的长条目。", 350)
    provider = _RawProvider(
        json.dumps(
            {
                "title": "优先级",
                "sections": [
                    {
                        "heading": "人工智能",
                        "items": [_item(long_normal, ["s1"]), _item(short_extra, ["s2"])],
                    }
                ],
                "limitations": [],
            },
            ensure_ascii=False,
        )
    )
    config = _config(
        targetReadingMinutes=1,
        columns=[{"name": "人工智能", "count": 1, "emptyPolicy": "hide"}],
    )
    row = run(
        _generate(
            config,
            provider,
            docs=[
                _doc("a", "2026-09-18T00:10:00+00:00"),
                _doc("b", "2026-09-18T00:20:00+00:00"),
            ],
        )
    )
    meta = json.loads(row["meta_json"])
    moved = {e["summary"] for e in meta["leftoverPool"]}
    assert short_extra in moved  # beyond-count 优先被移出（虽然更短）
    assert long_normal not in moved
    stored = json.loads(row["sections_json"])
    assert stored["sections"][0]["items"][0]["summary"] == long_normal


def test_n175_trim_preview_endpoint(client):
    """裁剪预览：before/after + 将移动的条目；零写入。"""
    run(
        _issues_store().upsert_issue(
            config_id=1,
            issue_key="2026-09-18",
            title="预览期",
            body_html="<p>x</p>",
            sections_json=json.dumps(
                {
                    "title": "预览期",
                    "sections": [
                        {
                            "heading": "要点",
                            "items": [
                                _item(_long_summary("甲。", 300), ["s1"]),
                                _item(_long_summary("乙。", 600), ["s1"]),
                            ],
                        }
                    ],
                    "limitations": [],
                },
                ensure_ascii=False,
            ),
            refs_json='{"s1": {"title": "T", "url": "https://a.example.com/x", "feedTitle": "F", "publishedAt": "2026-09-18T00:00:00+00:00"}}',
            model="m",
            published_at="2026-09-18T00:00:00+00:00",
        )
    )
    # 未启用：诚实说明，不裁剪
    off = client.get("/api/v1/gpt-digest/configs/1/issues/2026-09-18/trim-preview")
    assert off.status_code == 200
    body = off.json()
    assert body["targetReadingMinutes"] == 0
    assert body["moved"] == []
    assert body["beforeMinutes"] == body["afterMinutes"]
    assert "未启用" in (body["note"] or "")

    run(_config_store().update_config(1, {"targetReadingMinutes": 1}))
    on = client.get("/api/v1/gpt-digest/configs/1/issues/2026-09-18/trim-preview")
    assert on.status_code == 200
    body = on.json()
    assert body["targetReadingMinutes"] == 1
    assert body["beforeMinutes"] > body["afterMinutes"]
    assert len(body["moved"]) == 1
    assert body["moved"][0]["summary"].startswith("乙。")
    assert body["moved"][0]["refs"][0]["url"] == "https://a.example.com/x"
    # 预览零写入：期号内容不变
    row = run(_issues_store().get_issue(1, "2026-09-18"))
    assert len(json.loads(row["sections_json"])["sections"][0]["items"]) == 2


# ---- N176 引用去重（同事件聚合） ---------------------------------------------


def test_n176_same_event_clusters_with_per_source_provenance(client):
    """验收：同事件（标题相似 + 48h 内）聚合为一条多来源条目，逐来源
    保留出处；数字不一致时如实标注分歧。"""
    doc_a = _doc(
        "a",
        "2026-09-18T00:10:00+00:00",
        title="美联储宣布利率决议维持不变",
        content="据报道利率维持不变，资产负债表规模为100亿元。",
    )
    doc_b = _doc(
        "b",
        "2026-09-18T01:10:00+00:00",
        title="美联储利率决议维持不变",
        content="另一来源称资产负债表规模为120亿元，利率维持不变。",
    )
    doc_b["feedTitle"] = "另一示例源"
    provider = _RawProvider(
        _single_raw([_item("两来源报道了同一事件，规模数字存在差异。", ["s1", "s2"])])
    )
    config = _config(clusterEnabled=True)
    row = run(_generate(config, provider, draft=False, docs=[doc_a, doc_b]))
    stored = json.loads(row["sections_json"])
    assert len(stored["sections"][0]["items"]) == 1
    item = stored["sections"][0]["items"][0]
    assert sorted(item["sourceIds"]) == ["s1", "s2"]  # 逐来源引用
    assert "分歧" in (item["uncertainty"] or "")
    assert "100" in item["uncertainty"] and "120" in item["uncertainty"]
    meta = json.loads(row["meta_json"])
    assert meta["clusters"][0]["sourceIds"] == ["s1", "s2"]
    assert len(meta["clusters"][0]["titles"]) == 2
    # 渲染：条目列出每个来源各自的链接（来源出处可见）
    assert 'href="https://tech.example.com/a"' in row["body_html"]
    assert 'href="https://tech.example.com/b"' in row["body_html"]


def test_n176_same_title_different_dates_never_merges(client):
    """标题相似但相隔超过 48h → 绝不聚合（独立事件）。"""
    title = "美联储宣布利率决议维持不变"
    # 两篇都在 72h 选材窗口内（[now-72h, now)）但相隔 60h（> 48h 聚合窗）
    doc_old = _doc("old", "2026-09-15T12:00:00+00:00", title=title, content="旧文正文 50亿元。")
    doc_new = _doc("new", "2026-09-18T00:00:00+00:00", title=title, content="新文正文 80亿元。")
    provider = _RawProvider(
        _single_raw([_item("旧事件。", ["s1"]), _item("新事件。", ["s2"])])
    )
    config = _config(clusterEnabled=True, windowHours=72)
    row = run(_generate(config, provider, docs=[doc_old, doc_new]))
    meta = json.loads(row["meta_json"])
    assert "clusters" not in meta  # 无真实聚簇
    stored = json.loads(row["sections_json"])
    assert len(stored["sections"][0]["items"]) == 2  # 两条独立条目


def test_n176_cluster_disabled_by_default(client):
    """默认关闭：相同事件也不聚合（历史行为）。"""
    title = "央行宣布数字人民币试点扩大至十个城市"
    docs = [
        _doc("a", "2026-09-18T00:10:00+00:00", title=title),
        _doc("b", "2026-09-18T00:20:00+00:00", title=title),
    ]
    provider = _RawProvider(_single_raw([_item("一。", ["s1"]), _item("二。", ["s2"])]))
    adapter = _FakeAdapter(docs)
    row = run(
        generate_issue(
            _config_store(),
            _issues_store(),
            config=_config(clusterEnabled=False),
            adapter=adapter,
            ai_settings=_FakeAiSettings(),
            provider_factory=_ok_factory(provider),
            db=app.state.db,
            now=_fixed_now(),
        )
    )
    meta = json.loads(row["meta_json"])
    assert "clusters" not in meta


def test_n176_cluster_material_unit_and_staged_pipeline(client):
    """聚类单元：jaccard 阈值 + 时间窗；分阶段管线同样吃到聚合材料。"""
    from lumirss.gpt_digest import cluster_material

    same_a = _doc("a", "2026-09-18T00:00:00+00:00", title="苹果发布新款芯片性能翻倍")
    same_b = _doc("b", "2026-09-18T06:00:00+00:00", title="苹果芯片发布会：新款芯片性能翻倍")
    far_c = _doc("c", "2026-09-15T00:00:00+00:00", title="苹果发布新款芯片性能翻倍")  # >48h
    other = _doc("d", "2026-09-18T06:00:00+00:00", title="某地今日天气晴好气温回升")
    material = [same_a, same_b, far_c, other]
    clusters = cluster_material(material)
    groups = {tuple(group) for group in clusters}
    assert (0, 1) in groups or (1, 0) in groups  # 同事件聚合
    assert (0, 2) not in groups and (2, 0) not in groups  # 跨日不合并
    assert (0, 3) not in groups and (3, 0) not in groups  # 无关标题

    # 分阶段管线：选材 prompt 中出现「同一事件的多来源报道」合并行
    provider = _StagedProvider(
        _select_raw([["s1", "s2"]]),
        _single_raw([_item("聚合条目总结。", ["s1", "s2"])], heading="要点"),
        _single_raw([_item("聚合条目总结。", ["s1", "s2"])], heading="要点"),
    )
    adapter = _FakeAdapter([same_a, same_b])
    record: list[tuple] = []
    config = _config(clusterEnabled=True, stageModels={"summarize": "m-sum"})
    row = run(
        generate_issue(
            _config_store(),
            _issues_store(),
            config=config,
            adapter=adapter,
            ai_settings=_FakeAiSettings(),
            provider_factory=_ok_factory(provider, record),
            db=app.state.db,
            now=_fixed_now(),
        )
    )
    # 选材阶段的材料行被聚簇合并、system 附加聚合约束
    assert "同一事件的多来源报道" in provider.users[0]
    assert "同一事件的多来源报道" in provider.systems[0]
    meta = json.loads(row["meta_json"])
    assert meta["clusters"][0]["sourceIds"] == ["s1", "s2"]
