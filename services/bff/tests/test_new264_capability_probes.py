"""NEW-264 翻译服务能力比较 — 用户样本的显式对照探测。

- fake provider：无网络；
- 逐样本 结果/耗时/错误；零缓存行写入（ephemeral）；
- 未配置 → available=false + 诚实 reason；样本越界 → 422；
- 历史 cap=20；A/B 隔离。
"""

import asyncio
import json

import pytest

from lumirss.new264_capability_probes import (
    PROBE_HISTORY_CAP,
    ProbeInvalid,
    get_probe,
    list_probes,
    run_probe,
)
from lumirss.storage import Database
from new2xx_ab import ab_env  # noqa: F401

run = asyncio.run


@pytest.fixture(autouse=True)
def _allow_fixture_endpoints(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS", "127.0.0.1,ai.local")


def _fake_ai_factory(log):
    async def factory(base_url, model):
        log.append((base_url, model))

        class FakeProvider:
            async def complete(self, messages):
                text = messages[-1]["content"].split("\n\n", 1)[-1]
                return f"AI<{text}>"

        return FakeProvider()

    return factory


def _settings(baseUrl="http://ai.local/v1", model="m1"):
    return {
        "ai.base_url": baseUrl,
        "ai.model": model,
        "translation.language": "zh-CN",
        "translation.engine": "ai",
    }


def test_probe_runs_configured_side_ephemeral(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    ai_log: list = []
    report = run(
        run_probe(
            db,
            _settings(),
            [" Hello world. ", "Second sample."],
            _fake_ai_factory(ai_log),
        )
    )
    assert report.available is True
    assert report.samples == ["Hello world.", "Second sample."]
    ai = report.sides["ai"]
    assert ai["configured"]
    assert [s["text"] for s in ai["samples"]] == ["AI<Hello world.>", "AI<Second sample.>"]
    assert all(s["ok"] and s["elapsedMs"] >= 0 for s in ai["samples"])
    # AI 侧工厂每报告只构建一次（provider 复用）
    assert len(ai_log) == 1

    # ephemeral：绝不写段缓存行
    rows = run(db.fetch_all("SELECT * FROM ai_translation_segments"))
    assert rows == []

    # 台账可回看
    stored = run(get_probe(db, report.id))
    assert stored is not None
    assert json.dumps(stored["sides"])  # 结构完整
    assert run(list_probes(db))[0]["id"] == report.id


def test_probe_unconfigured_honest_and_validation(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    report = run(
        run_probe(db, _settings(baseUrl="", model=""), ["样本"], None)
    )
    assert report.available is False
    assert "没有已配置" in report.reason
    assert report.sides["ai"]["configured"] is False

    with pytest.raises(ProbeInvalid):
        run(run_probe(db, _settings(), [], None))
    with pytest.raises(ProbeInvalid):
        run(run_probe(db, _settings(), ["a", "b", "c", "d", "e", "f"], None))
    with pytest.raises(ProbeInvalid):
        run(run_probe(db, _settings(), ["x" * 501], None))
    with pytest.raises(ProbeInvalid):
        run(run_probe(db, _settings(), ["   "], None))


def test_probe_history_cap(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    for _ in range(PROBE_HISTORY_CAP + 2):
        run(run_probe(db, _settings(baseUrl="", model=""), ["样本"], None))
    rows = run(db.fetch_all("SELECT id FROM translation_capability_probes"))
    assert len(rows) == PROBE_HISTORY_CAP
    assert len(run(list_probes(db, limit=99))) == PROBE_HISTORY_CAP


# ---------------------------------------------------------------------------
# API 行为
# ---------------------------------------------------------------------------


def test_api_probe_unconfigured_and_history(client):
    made = client.post(
        "/api/v1/translation/capability-probe",
        json={"samples": ["一段非敏感样本。"]},
    )
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["available"] is False
    assert "没有已配置" in body["reason"]

    listed = client.get("/api/v1/translation/capability-probe").json()["probes"]
    assert [p["id"] for p in listed] == [body["id"]]

    single = client.get(f"/api/v1/translation/capability-probe/{body['id']}")
    assert single.status_code == 200
    assert client.get("/api/v1/translation/capability-probe/tcp-404").status_code == 404

    bad = client.post(
        "/api/v1/translation/capability-probe", json={"samples": []}
    )
    assert bad.status_code == 422
    # 空 samples 在请求模型层就被拒（应用统一 422 形状）
    assert bad.json()["error"]["type"] == "invalid_request"


# ---------------------------------------------------------------------------
# A/B 隔离
# ---------------------------------------------------------------------------


def test_ab_probe_history_isolated(ab_env):  # noqa: F811
    env = ab_env
    client = env["client"]
    made_a = client.post(
        "/api/v1/translation/capability-probe",
        json={"samples": ["A 的样本"]},
        headers=env["a"],
    )
    made_b = client.post(
        "/api/v1/translation/capability-probe",
        json={"samples": ["B 的样本"]},
        headers=env["b"],
    )
    assert made_a.status_code == 200 and made_b.status_code == 200

    a_list = client.get(
        "/api/v1/translation/capability-probe", headers=env["a"]
    ).json()["probes"]
    b_list = client.get(
        "/api/v1/translation/capability-probe", headers=env["b"]
    ).json()["probes"]
    assert [p["samples"] for p in a_list] == [["A 的样本"]]
    assert [p["samples"] for p in b_list] == [["B 的样本"]]

    cross = client.get(
        f"/api/v1/translation/capability-probe/{made_b.json()['id']}",
        headers=env["a"],
    )
    assert cross.status_code == 404
