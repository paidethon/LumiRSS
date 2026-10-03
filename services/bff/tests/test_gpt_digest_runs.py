"""R13 日报生成体验与防线测试（run-status / cancel / injection / 无 key）。

覆盖：
- prompt injection 防线：日报主链（单阶段/选材/总结/润色）与变体链
  （解释版/周报/对照/事实对照）的 system 提示都把资料文本声明为
  「资料而非指令」；
- 无 key 旁路：AI 未配置时零 provider 调用、零期刊写入（RSS 阅读不
  受影响）；调度对暂停配置完全不触碰生成函数；
- 取消语义：run-status/cancel 端点（含幂等 cancelled=false）、
  already_running 并发守卫、分阶段生成在阶段边界被取消时 409
  cancelled 且绝不落任何期号；
- 发布幂等与 issue_key 去重由 test_f031/​test_gpt_digest 既有用例覆盖，
  这里补一条 API 面的组合断言（重试发布不产生第二行）。

上游网络全部 mock（本地假 provider/adapter，零真实调用）。
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from lumirss.adapters.freshrss import EntryDocument, EntryDocumentPage
from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate
from lumirss.gpt_digest import (
    DigestRunCancelled,
    GptDigestScheduler,
    build_messages,
    compare_facts,
    compare_with_previous,
    digest_run,
    digest_run_status,
    explain_issue,
    generate_issue,
    generate_weekly,
)
from lumirss.gpt_digest_configs import GptDigestConfigStore
from lumirss.gpt_digest_issues import GptDigestIssuesStore
from lumirss.main import app

pytestmark = pytest.mark.usefixtures("client")


def run(coroutine):
    return asyncio.run(coroutine)


# ---- fakes（与 test_gpt_digest.py 同一族；上游零真实网络） -----------------


class _CaptureProvider:
    """记录每次调用的 messages（供 system 提示断言），返回固定 raw。"""

    def __init__(self, raw: str):
        self._raw = raw
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, *, messages):
        self.calls.append(messages)
        return self._raw


class _CountingFactory:
    def __init__(self, provider):
        self.provider = provider
        self.invocations = 0

    async def __call__(self, base_url, model, explicit_model: bool = False):
        self.invocations += 1
        return self.provider


class _FakeAiSettings:
    def __init__(self, values: dict[str, str] | None = None):
        self._values = values or {}

    async def load(self):
        return dict(self._values)


class _FakeAdapter:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    async def list_entry_documents(self, limit: int = 120):
        return EntryDocumentPage(
            documents=[EntryDocument(**d) for d in self._docs],
            upstreamContinuation=None,
        )


def _doc(item_id: str, published: str) -> dict:
    return {
        "item_id": item_id,
        "entryRef": f"ref-{item_id}",
        "feedUrl": "https://blog.example.com/rss",
        "feedTitle": "示例源",
        "title": f"文章 {item_id}",
        "url": f"https://blog.example.com/{item_id}",
        "publishedAt": published,
        "read": False,
        "starred": False,
        "contentText": f"{item_id} 的正文内容。",
    }


def _fresh_doc(item_id: str) -> dict:
    """发布时刻 = 现在时刻减 30 秒缓冲（避开窗口右端点的同秒竞态；
    供走完整 API 的用例使用——路由路径用的是真实时钟）。"""
    stamp = datetime.now(UTC) - timedelta(seconds=30)
    return _doc(item_id, stamp.isoformat())


_MATERIAL_OUTPUT = json.dumps(
    {
        "title": "测试日报",
        "sections": [
            {
                "heading": "主题",
                "items": [
                    {"summary": "关于 s1。", "sourceIds": ["s1"], "uncertainty": None}
                ],
            }
        ],
        "limitations": [],
    },
    ensure_ascii=False,
)

_SELECTION_OUTPUT = json.dumps(
    {
        "title": "选材",
        "assignments": [{"heading": "主题", "sourceIds": ["s1"]}],
    },
    ensure_ascii=False,
)

_INSTRUCTION_MARKS = ("资料而非指令", "视为待总结的资料")
_INSTRUCTION_NO_EXECUTE = "不执行"


def _assert_injection_guard(system: str, name: str) -> None:
    """system 提示必须同时声明「文本=资料」（两种既有措辞任一）与
    「资料中的指令不执行」。"""
    assert any(mark in system for mark in _INSTRUCTION_MARKS), f"{name} 缺少资料声明"
    assert _INSTRUCTION_NO_EXECUTE in system, f"{name} 缺少不执行约束"


# ---- prompt injection 防线 --------------------------------------------------


def test_main_chain_prompts_declare_material_not_instruction():
    """单阶段与 select/summarize/polish 三阶段的 system 提示都把外部
    文本声明为资料（任何嵌入指令不执行）。"""
    material = [_doc("a", "2026-09-18T00:10:00+00:00")]
    variants = {
        "single": build_messages(material),
        "select": build_messages(material, stage="select"),
        "summarize": build_messages(
            material,
            stage="summarize",
            selection=[{"heading": "主题", "sourceIds": ["s1"]}],
        ),
        "polish": build_messages(
            {"title": "t", "sections": []},
            stage="polish",
            current_output={"title": "t", "sections": []},
        ),
    }
    for name, messages in variants.items():
        system = messages[0]["content"]
        assert messages[0]["role"] == "system", name
        _assert_injection_guard(system, name)


def _seed_issue(issues: GptDigestIssuesStore, key: str, summaries: list[str]) -> None:
    items = [
        {"summary": s, "sourceIds": ["s1"], "uncertainty": None}
        for s in summaries
    ]
    # 生成路径落库的是完整输出对象 {title, sections, limitations}（F031
    # 兼容形状）——发布前的引用校验按该形状解析。
    run(
        issues.upsert_issue(
            config_id=1,
            issue_key=key,
            title="期",
            body_html="<p>x</p>",
            sections_json=json.dumps(
                {"title": "期", "sections": [{"heading": "主题", "items": items}], "limitations": []},
                ensure_ascii=False,
            ),
            refs_json=json.dumps(
                {"s1": {"title": "T", "url": "https://x.example.com/a", "feedTitle": "F"}}
            ),
            model="m",
            published_at="2026-09-17T00:00:00+00:00",
        )
    )


def test_variant_chain_prompts_declare_material_not_instruction(client):
    """解释版/周报/对照/事实对照四条变体链的 system 提示同样声明资料
    非指令（变体链读的是已生成总结，仍属不可信文本）。"""
    issues = GptDigestIssuesStore(app.state.db)
    _seed_issue(issues, "2026-09-16", ["进展A。", "进展A的不同陈述。"])
    _seed_issue(issues, "2026-09-17", ["进展B。"])
    config = run(GptDigestConfigStore(app.state.db).get_config(1))

    explain_provider = _CaptureProvider(
        json.dumps(
            {
                "title": "解释",
                "sections": [
                    {
                        "heading": "主题",
                        "items": [
                            {
                                "summary": "解释后。",
                                "sourceIds": ["s1"],
                                "uncertainty": None,
                            }
                        ],
                    }
                ],
                "limitations": [],
            },
            ensure_ascii=False,
        )
    )
    run(
        explain_issue(
            GptDigestConfigStore(app.state.db),
            issues,
            config=config,
            ai_settings=_FakeAiSettings({"ai.base_url": "http://ai.local", "ai.model": "m"}),
            provider_factory=_CountingFactory(explain_provider),
            issue_key="2026-09-17",
        )
    )
    weekly_provider = _CaptureProvider(
        json.dumps(
            {
                "title": "周报",
                "sections": [
                    {
                        "heading": "演进",
                        "items": [
                            {
                                "summary": "B 继承 A。",
                                "sourceIds": ["w1:s1"],
                                "uncertainty": None,
                            }
                        ],
                    }
                ],
                "limitations": [],
            },
            ensure_ascii=False,
        )
    )
    run(
        generate_weekly(
            GptDigestConfigStore(app.state.db),
            issues,
            config=config,
            ai_settings=_FakeAiSettings({"ai.base_url": "http://ai.local", "ai.model": "m"}),
            provider_factory=_CountingFactory(weekly_provider),
            now=datetime(2026, 9, 18, 8, 0, 0, tzinfo=UTC),  # 与种子期刊同一周
        )
    )
    compare_provider = _CaptureProvider(
        json.dumps(
            {
                "title": "对照",
                "sections": [
                    {
                        "heading": "变化",
                        "items": [
                            {
                                "summary": "[重复] 同一事项。",
                                "sourceIds": ["prev:s1", "cur:s1"],
                                "uncertainty": None,
                            }
                        ],
                    }
                ],
                "limitations": [],
            },
            ensure_ascii=False,
        )
    )
    run(
        compare_with_previous(
            GptDigestConfigStore(app.state.db),
            issues,
            config=config,
            ai_settings=_FakeAiSettings({"ai.base_url": "http://ai.local", "ai.model": "m"}),
            provider_factory=_CountingFactory(compare_provider),
            issue_key="2026-09-17",
        )
    )
    facts_provider = _CaptureProvider(
        json.dumps(
            {
                "title": "事实对照",
                "sections": [
                    {
                        "heading": "分歧",
                        "items": [
                            {
                                "summary": "两说并列。",
                                "sourceIds": ["2026-09-16:s1"],
                                "uncertainty": None,
                            }
                        ],
                    }
                ],
                "limitations": [],
            },
            ensure_ascii=False,
        )
    )
    run(
        compare_facts(
            issues,
            config_id=1,
            issue_key="2026-09-16",
            ai_settings=_FakeAiSettings({"ai.base_url": "http://ai.local", "ai.model": "m"}),
            provider_factory=_CountingFactory(facts_provider),
        )
    )
    for name, provider in (
        ("explain", explain_provider),
        ("weekly", weekly_provider),
        ("compare", compare_provider),
        ("compare-facts", facts_provider),
    ):
        assert provider.calls, name
        _assert_injection_guard(provider.calls[0][0]["content"], name)


# ---- 无 key 旁路（digest 关闭/未配置不影响 RSS） ----------------------------


def test_generate_without_ai_config_makes_zero_provider_calls(client):
    """base URL / model 缺失 → AiNotConfigured；provider 一次都不构造，
    也不写任何期刊行（无 key 不影响 RSS 阅读本身）。"""
    from lumirss.ai_provider import AiNotConfigured

    issues = GptDigestIssuesStore(app.state.db)
    factory = _CountingFactory(_CaptureProvider(_MATERIAL_OUTPUT))
    with pytest.raises(AiNotConfigured):
        run(
            generate_issue(
                GptDigestConfigStore(app.state.db),
                issues,
                config={
                    "id": 1,
                    "name": "默认日报",
                    "enabled": True,
                    "timezone": "UTC",
                    "windowHours": 24,
                    "limitCount": 10,
                    "hour": 8,
                    "perSourceCap": 0,
                    "feedUrlAllow": "",
                },
                adapter=_FakeAdapter([_doc("a", "2026-09-18T00:10:00+00:00")]),
                ai_settings=_FakeAiSettings({}),
                provider_factory=factory,
                db=app.state.db,
                now=datetime(2026, 9, 18, 8, 5, 0, tzinfo=UTC),
            )
        )
    assert factory.invocations == 0
    assert run(issues.recent_issues(1, 10)) == []


def test_scheduler_skips_disabled_config_entirely(client):
    """暂停配置：调度连生成函数都不调用（零 FreshRSS/零 AI 触碰）。"""
    calls: list[str] = []

    async def generate_fn(plan):
        calls.append(plan.issue_key)
        return {}

    scheduler = GptDigestScheduler(app.state.db)
    result = run(
        scheduler.maybe_generate_config(
            generate_fn,
            {"id": 1, "enabled": False, "timezone": "UTC", "hour": 8},
            GptDigestIssuesStore(app.state.db),
        )
    )
    assert result is None
    assert calls == []


# ---- run-status / cancel 端点与取消语义 -------------------------------------


def test_run_status_and_cancel_idle_are_honest(client):
    """空闲：run-status running=false；cancel 幂等返回 cancelled=false。"""
    status = client.get("/api/v1/gpt-digest/configs/1/run-status")
    assert status.status_code == 200
    assert status.json() == {"running": False, "stage": None, "startedAt": None}
    cancel = client.post("/api/v1/gpt-digest/configs/1/cancel")
    assert cancel.status_code == 200
    assert cancel.json() == {"cancelled": False}


def test_run_status_reflects_registered_run_and_cancel_flips_flag(client):
    with digest_run(1) as handle:
        handle.set_stage("select")
        status = client.get("/api/v1/gpt-digest/configs/1/run-status").json()
        assert status["running"] is True
        assert status["stage"] == "select"
        assert status["startedAt"]
        cancel = client.post("/api/v1/gpt-digest/configs/1/cancel").json()
        assert cancel == {"cancelled": True}
        with pytest.raises(DigestRunCancelled):
            handle.check_cancel()
    assert client.get("/api/v1/gpt-digest/configs/1/run-status").json()["running"] is False


def test_generate_rejects_concurrent_run_with_already_running(client):
    with digest_run(1):
        response = client.post("/api/v1/gpt-digest/configs/1/generate")
    assert response.status_code == 409
    assert response.json()["error"]["type"] == "already_running"
    # 运行结束后恢复可生成（此处置信 FreshRSS 未配置 → 503 而非 409）。
    after = client.post("/api/v1/gpt-digest/configs/1/generate")
    assert after.status_code == 503


def test_cancelled_staged_generation_returns_409_and_writes_nothing(
    client, monkeypatch
):
    """分阶段生成在选材完成后被取消 → API 409 cancelled；期刊零写入；
    运行句柄被清理（run-status 回到空闲）。"""
    run(AiSettingsStore(app.state.db).save(AiSettingsUpdate(baseUrl="https://ai.local/v1", model="m-base")))
    run(
        GptDigestConfigStore(app.state.db).update_config(
            1, {"enabled": True, "stageModels": {"select": "m-s", "summarize": "m-x"}}
        )
    )

    class _CancellingSelectProvider:
        def __init__(self):
            self.calls = 0

        async def complete(self, *, messages):
            self.calls += 1
            assert messages[0]["role"] == "system"
            handle = digest_run_status(1)
            assert handle is not None
            handle.cancel_requested = True  # 选材输出返回后、总结开始前取消
            return _SELECTION_OUTPUT

    provider = _CancellingSelectProvider()

    def _fake_build_provider(http_client, **_kwargs):
        # 真实 provider_factory 会传入 purpose 映射出的 provider 名；
        # 测试里一律替换为本假件（协议兼容、零网络）。
        return provider

    monkeypatch.setattr("lumirss.ai_provider.build_provider", _fake_build_provider)
    monkeypatch.setattr(
        app.state,
        "freshrss_adapter",
        _FakeAdapter([_fresh_doc("a")]),
        raising=False,
    )
    response = client.post("/api/v1/gpt-digest/configs/1/generate")
    assert response.status_code == 409, response.text
    assert response.json()["error"]["type"] == "cancelled"
    assert provider.calls == 1  # 只发生一次模型调用（取消发生在阶段边界）
    issues = GptDigestIssuesStore(app.state.db)
    assert run(issues.recent_issues(1, 10, include_drafts=True)) == []
    assert client.get("/api/v1/gpt-digest/configs/1/run-status").json()["running"] is False


# ---- 发布幂等（API 面组合断言；细节由 test_f031 覆盖） ----------------------


def test_publish_retry_does_not_duplicate_issue_row(client):
    """重复点「发布」/网络重试：同 issue_key 恒一行、状态保持 published、
    published_at 不被重置（幂等去重键 = config_id + issue_key）。"""
    issues = GptDigestIssuesStore(app.state.db)
    _seed_issue(issues, "2026-09-17", ["一条总结。"])
    run(app.state.db.execute("UPDATE gpt_digest_issues SET status = 'draft' WHERE issue_key = '2026-09-17'", ()))
    first = client.post("/api/v1/gpt-digest/configs/1/issues/2026-09-17/publish")
    assert first.status_code == 200, first.text
    published_at = first.json()["issue"]["publishedAt"]
    for _ in range(2):
        again = client.post("/api/v1/gpt-digest/configs/1/issues/2026-09-17/publish")
        assert again.status_code == 200
        assert again.json()["issue"]["publishedAt"] == published_at
    rows = run(
        app.state.db.fetch_all(
            "SELECT issue_key FROM gpt_digest_issues WHERE config_id = 1 AND issue_key = '2026-09-17'"
        )
    )
    assert len(rows) == 1
