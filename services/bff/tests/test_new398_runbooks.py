"""NEW-398 错误自助处理单 — 注册表真实错误码、逐步效果、脱敏升级材料。"""

from lumirss.config import LumiSettings
from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册


def test_new398_registry_and_step_recording(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    registry = client.get("/api/v1/support/runbooks", headers=a).json()
    codes = {rb["code"] for rb in registry["runbooks"]}
    assert {"connection_error", "ai_not_configured",
            "rsshub_not_configured"} <= codes
    book = next(rb for rb in registry["runbooks"] if rb["code"] == "connection_error")
    assert len(book["steps"]) >= 2
    # 开单 + 逐步记录（覆盖式：重复记录同一步 = 更新）
    opened = client.post(
        "/api/v1/support/runbooks/connection_error/sessions", headers=a
    )
    assert opened.status_code == 201, opened.text
    session = opened.json()
    first = client.post(
        f"/api/v1/support/runbooks/sessions/{session['id']}/steps",
        json={"stepIndex": 1, "outcome": "tried", "note": "面板显示配置齐备"},
        headers=a,
    )
    assert first.status_code == 200, first.text
    overwritten = client.post(
        f"/api/v1/support/runbooks/sessions/{session['id']}/steps",
        json={"stepIndex": 1, "outcome": "no_effect"},
        headers=a,
    )
    assert overwritten.status_code == 200
    client.post(
        f"/api/v1/support/runbooks/sessions/{session['id']}/steps",
        json={"stepIndex": 2, "outcome": "helped"},
        headers=a,
    )
    detail = client.get(
        f"/api/v1/support/runbooks/sessions/{session['id']}", headers=a
    ).json()
    assert detail["status"] == "open"
    outcomes = {o["stepIndex"]: o["outcome"] for o in detail["outcomes"]}
    assert outcomes == {1: "no_effect", 2: "helped"}
    # 校验：未知步骤 / 坏结果 / 未知错误码
    assert (
        client.post(
            f"/api/v1/support/runbooks/sessions/{session['id']}/steps",
            json={"stepIndex": 99, "outcome": "tried"},
            headers=a,
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/support/runbooks/sessions/{session['id']}/steps",
            json={"stepIndex": 1, "outcome": "magic"},
            headers=a,
        ).status_code
        == 422
    )
    assert (
        client.post("/api/v1/support/runbooks/not-a-code/sessions", headers=a).status_code
        == 404
    )


def test_new398_escalation_material_is_sanitized(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    session = client.post(
        "/api/v1/support/runbooks/ai_not_configured/sessions", headers=a
    ).json()
    client.post(
        f"/api/v1/support/runbooks/sessions/{session['id']}/steps",
        json={"stepIndex": 1, "outcome": "tried"},
        headers=a,
    )
    escalated = client.post(
        f"/api/v1/support/runbooks/sessions/{session['id']}/escalate",
        json={"note": "按步骤处理后仍失败，求助。"},
        headers=a,
    )
    assert escalated.status_code == 200, escalated.text
    material = escalated.json()["material"]
    # 只含：错误码 + 版本 + 步骤结果 + 用户备注
    assert set(material.keys()) == {"code", "version", "steps", "userNote",
                                    "generatedAt"}
    assert material["code"] == "ai_not_configured"
    assert material["version"] == LumiSettings().LUMIRSS_VERSION
    assert material["steps"] == [{"stepIndex": 1, "outcome": "tried"}]
    flat = str(material)
    assert "cookie" not in flat and a["cookie"].split("=")[1] not in flat
    assert ab_env["a"]["userId"] not in flat
    # resolve 终态
    resolved = client.post(
        f"/api/v1/support/runbooks/sessions/{session['id']}/resolve", headers=a
    ).json()
    assert resolved["status"] == "resolved"


def test_new398_ab_isolation(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    session = client.post(
        "/api/v1/support/runbooks/connection_error/sessions", headers=a
    ).json()
    # B 看不到 / 改不了 A 的处理单
    listing_b = client.get("/api/v1/support/runbooks/sessions", headers=b).json()
    assert listing_b["sessions"] == []
    assert (
        client.get(
            f"/api/v1/support/runbooks/sessions/{session['id']}", headers=b
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/support/runbooks/sessions/{session['id']}/steps",
            json={"stepIndex": 1, "outcome": "skipped"},
            headers=b,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/support/runbooks/sessions/{session['id']}/resolve", headers=b
        ).status_code
        == 404
    )
    # A 的单不受影响
    detail = client.get(
        f"/api/v1/support/runbooks/sessions/{session['id']}", headers=a
    ).json()
    assert detail["outcomes"] == []
