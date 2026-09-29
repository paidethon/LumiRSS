"""NEW-348 数据驻留说明页 — 配置推导/未知项如实标注/管理员注释
（admin 写、成员只读）+ A/B 隔离。（零网络调用）"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册

RESIDENCY_PATH = "/api/v1/privacy/data-residency"
NOTES_PATH = "/api/v1/admin/residency-notes"


def test_new348_sections_and_unknown_honesty(ab_env):  # noqa: F811
    """遥测=无外发（按实际构建 known）；推导不出的键如实 unknown 并
    提示管理员补充。"""
    client = ab_env["client"]
    response = client.get(RESIDENCY_PATH, headers=ab_env["a"])
    assert response.status_code == 200, response.text
    payload = response.json()
    keys = {section["key"] for section in payload["sections"]}
    assert {"article_body", "backups", "ai_requests", "telemetry"} <= keys
    telemetry = next(s for s in payload["sections"] if s["key"] == "telemetry")
    assert telemetry["known"] is True
    assert "不内置遥测" in telemetry["detail"]
    assert "请管理员" in payload["unknownHint"]
    for section in payload["sections"]:
        if not section["known"]:
            assert section["key"] in payload["unknownKeys"]


def test_new348_admin_note_visible_to_members(ab_env):  # noqa: F811
    client = ab_env["client"]
    put = client.put(
        NOTES_PATH,
        json={"key": "backups", "note": "备份盘为机房 A 的加密盘，每日校验。"},
        headers=ab_env["owner"],
    )
    assert put.status_code == 200, put.text

    member_view = client.get(RESIDENCY_PATH, headers=ab_env["b"]).json()
    backups = next(s for s in member_view["sections"] if s["key"] == "backups")
    assert backups["adminNote"] == "备份盘为机房 A 的加密盘，每日校验。"

    # 非 admin（成员 B）写注释 → 403。
    forbidden = client.put(
        NOTES_PATH,
        json={"key": "hosting_provider", "note": "不应成功"},
        headers=ab_env["b"],
    )
    assert forbidden.status_code == 403

    admin_list = client.get(NOTES_PATH, headers=ab_env["owner"]).json()["items"]
    assert any(item["key"] == "backups" for item in admin_list)


def test_new348_note_validation_and_delete(ab_env):  # noqa: F811
    client = ab_env["client"]
    bad_key = client.put(
        NOTES_PATH,
        json={"key": "Bad Key!", "note": "x"},
        headers=ab_env["owner"],
    )
    assert bad_key.status_code == 422
    custom = client.put(
        NOTES_PATH,
        json={"key": "hosting_provider", "note": "自营单机（wsl2 主机）"},
        headers=ab_env["owner"],
    )
    assert custom.status_code == 200
    deleted = client.delete(
        f"{NOTES_PATH}/hosting_provider", headers=ab_env["owner"]
    )
    assert deleted.status_code == 200
    missing = client.delete(
        f"{NOTES_PATH}/hosting_provider", headers=ab_env["owner"]
    )
    assert missing.status_code == 404


def test_new348_build_view_pure():
    from lumirss.new348_data_residency import build_residency_view

    payload = build_residency_view(
        freshrss_host=None,
        rsshub_host="rsshub.example",
        ai_host=None,
        webdav_host=None,
        webdav_ready=False,
        notes={},
    )
    assert "freshrss_instance" in payload["unknownKeys"]
    rsshub = next(s for s in payload["sections"] if s["key"] == "rsshub_instance")
    assert rsshub["known"] is True and "rsshub.example" in rsshub["detail"]
    assert payload["sections"][0]["adminNote"] is None
