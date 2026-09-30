"""NEW-397 实例服务状态页 — 本地真实检测、台账历史、无虚构可用率。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册

SURFACE_KEYS = {"control_db", "freshrss", "rsshub", "ai"}
ALLOWED_STATUSES = {"ok", "unconfigured", "fail", "unknown"}


def test_new397_check_records_real_results(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    # 未检测前：unknown，无编造
    page = client.get("/api/v1/status/services", headers=a).json()
    assert {s["key"] for s in page["surfaces"]} == SURFACE_KEYS
    assert all(s["status"] == "unknown" and s["checkedAt"] is None
               for s in page["surfaces"])
    # 执行检测：控制库本地 SELECT 1 必然可测；其余按配置真实报告
    checked = client.post("/api/v1/status/services/check", headers=a)
    assert checked.status_code == 200, checked.text
    body = checked.json()
    by_key = {s["key"]: s for s in body["surfaces"]}
    assert by_key["control_db"]["status"] == "ok"
    assert "迁移" in by_key["control_db"]["detail"]
    for key in SURFACE_KEYS:
        assert by_key[key]["status"] in {"ok", "unconfigured", "fail"}
        assert by_key[key]["checkedAt"] is not None
    # 控制库的「最近检测时间」是台账里的真实时间，历史可回看
    page_after = client.get("/api/v1/status/services", headers=a).json()
    control = next(s for s in page_after["surfaces"] if s["key"] == "control_db")
    assert control["history"], "检测后历史不应为空"
    assert all(h["status"] in ALLOWED_STATUSES for h in control["history"])
    # 两次检测 → 历史增长（真实台账，不是静态文案）
    client.post("/api/v1/status/services/check", headers=a)
    page_third = client.get("/api/v1/status/services", headers=a).json()
    control_third = next(
        s for s in page_third["surfaces"] if s["key"] == "control_db"
    )
    assert len(control_third["history"]) == 2
    # 绝不出现可用率/百分比字段
    flat = str(page_third)
    assert "uptime" not in flat.lower() and "availability" not in flat.lower()
    assert "%" not in flat


def test_new397_requires_login(ab_env):  # noqa: F811
    from fastapi.testclient import TestClient

    # 全新客户端（无会话 cookie）：实例级页面拒绝匿名访问
    fresh = TestClient(ab_env["app"], base_url="http://lumirss.test")
    assert fresh.get("/api/v1/status/services").status_code == 401
    assert fresh.post("/api/v1/status/services/check").status_code == 401
    # 成员 A/B 之间没有交叉数据可泄露（页面是实例级只读检测台账）
    client = ab_env["client"]
    a_page = client.get("/api/v1/status/services", headers=ab_env["a"]).json()
    b_page = client.get("/api/v1/status/services", headers=ab_env["b"]).json()
    assert a_page == b_page
