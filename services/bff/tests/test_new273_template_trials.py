"""NEW-273 提示模板试运行 — 逐样本试跑 / 用量台账 / 显式启用。"""

from fastapi.testclient import TestClient

from lumirss.ai_provider import AiTimeout
from lumirss.main import app
from lumirss.storage import Database
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册
from new271_helpers import FakeProvider, configure_ai
from new271_helpers import deps_factory as _deps_factory

SAMPLES = [
    {"title": "合成样本一", "text": "样本正文一，讲述温度对反应速率的影响。"},
    {"title": "本人样本二", "text": "样本正文二，讲述城市化与通勤行为。"},
]


def _setup(monkeypatch, outputs: list[str] | None = None,
           errors: list | None = None, configure: bool = True):
    provider = FakeProvider(outputs=outputs, errors=errors)
    db = Database(f"{_tmp()}/lumi.sqlite")
    if configure:
        configure_ai(db)
    monkeypatch.setattr(
        "lumirss.deps._provider_factory_for", _deps_factory(provider)
    )
    return db, provider


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()


def test_new273_trial_run_usage_and_promote(monkeypatch):
    """两个样本各一次真实调用；inputChars/输出如实入台账；promote 启用。"""
    db, provider = _setup(monkeypatch, outputs=["结果一", "结果二"])
    with TestClient(app) as client:
        app.state.db = db
        run = client.post(
            "/api/v1/ai/template-trials",
            json={
                "templateText": "请为正文提取三个关键要点",
                "samples": SAMPLES,
                "sampleKind": "custom",
            },
        )
        assert run.status_code == 201, run.text
        trial = run.json()
        assert provider.calls == 2  # 实际用量 = 样本数
        assert [r["status"] for r in trial["results"]] == ["success", "success"]
        assert trial["results"][0]["output"] == "结果一"
        assert trial["results"][0]["inputChars"] > 0
        assert trial["promotedTemplateId"] is None

        listing = client.get("/api/v1/ai/template-trials").json()
        assert listing["total"] == 1

        promote = client.post(
            f"/api/v1/ai/template-trials/{trial['id']}/promote",
            json={"name": "要点提取模板"},
        )
        assert promote.status_code == 200, promote.text
        promoted_id = promote.json()["promotedTemplateId"]
        assert promoted_id

        # 模板真的进了 F030 的正式面
        templates = client.get("/api/v1/qa-templates").json()
        assert any(t["id"] == promoted_id for t in templates["items"])

        # 再次 promote 幂等（不重复建模板）
        again = client.post(
            f"/api/v1/ai/template-trials/{trial['id']}/promote",
            json={"name": "改名也不重复"},
        ).json()
        assert again["promotedTemplateId"] == promoted_id
        assert len(client.get("/api/v1/qa-templates").json()["items"]) == 1


def test_new273_failed_sample_recorded_honestly(monkeypatch):
    """样本失败如实记录 errorType，不估算也不掩盖。"""
    db, provider = _setup(
        monkeypatch,
        outputs=["成功结果"],
        errors=[AiTimeout("试跑超时")],
    )
    with TestClient(app) as client:
        app.state.db = db
        run = client.post(
            "/api/v1/ai/template-trials",
            json={
                "templateText": "模板",
                "samples": SAMPLES,
                "sampleKind": "synthetic",
            },
        )
        assert run.status_code == 201, run.text
        results = run.json()["results"]
        assert results[0]["status"] == "failed"
        assert results[0]["errorType"] == "AiTimeout"
        assert results[1]["status"] == "success"


def test_new273_validation_and_unconfigured(monkeypatch):
    """样本数/内容校验 422；未配置 provider → 503 ai_not_configured。"""
    db, _provider = _setup(monkeypatch, configure=False)
    with TestClient(app) as client:
        app.state.db = db
        empty = client.post(
            "/api/v1/ai/template-trials",
            json={"templateText": "模板", "samples": []},
        )
        assert empty.status_code == 422
        too_many = client.post(
            "/api/v1/ai/template-trials",
            json={
                "templateText": "模板",
                "samples": [
                    {"title": f"s{i}", "text": "x"} for i in range(4)
                ],
            },
        )
        assert too_many.status_code == 422
        assert (
            client.get("/api/v1/ai/template-trials/no-such").status_code == 404
        )
        unconfigured = client.post(
            "/api/v1/ai/template-trials",
            json={
                "templateText": "模板",
                "samples": [{"title": "s", "text": "x"}],
            },
        )
        assert unconfigured.status_code == 503
        assert unconfigured.json()["error"]["type"] == "ai_not_configured"


def test_new273_cross_user_trials_isolated(ab_env, monkeypatch):  # noqa: F811
    """A 的试跑台账对 B 不可见；B 的启用不受 A 的试跑影响。"""
    provider = FakeProvider(outputs=["A 的试跑输出"])
    monkeypatch.setattr(
        "lumirss.deps._provider_factory_for", _deps_factory(provider)
    )
    env = ab_env
    client = env["client"]
    # A/B 各自配置 base/model（未配置 → 503；走 PUT 全局设置）
    for who in ("a", "b"):
        put = client.put(
            "/api/v1/settings/ai",
            json={"baseUrl": "https://api.example.com/v1", "model": "m"},
            headers=env[who],
        )
        assert put.status_code == 200, put.text
    trial = client.post(
        "/api/v1/ai/template-trials",
        json={
            "templateText": "A 的模板",
            "samples": [{"title": "s", "text": "样本"}],
        },
        headers=env["a"],
    )
    assert trial.status_code == 201, trial.text
    assert (
        client.get("/api/v1/ai/template-trials", headers=env["b"]).json()["total"]
        == 0
    )
    assert (
        client.get(
            f"/api/v1/ai/template-trials/{trial.json()['id']}", headers=env["b"]
        ).status_code
        == 404
    )
