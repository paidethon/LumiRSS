"""NEW-380 运维交接摘要 — 按真实记录生成脱敏清单 → 确认（step-up）
→ 导出（未确认 409）；清单含未完成项，不含任何秘密值。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new37x_helpers import step_up_headers


def test_new380_build_lists_real_open_items(ab_env):  # noqa: F811
    """生成的清单如实反映既有的未完成项：工单 / 任务暂停 / 配置草案
    / 排程窗口，每项都能对上真实记录。"""
    client = ab_env["client"]
    owner = ab_env["owner"]

    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    ticket = client.post(
        "/api/v1/support/tickets",
        headers=ab_env["a"],
        json={"subject": "交接前的尾巴", "body": "还开着。"},
    ).json()
    client.post(
        "/api/v1/admin/task-calendar/mail_imap/pause",
        headers=step_up_headers(client, owner, "task_kind_pause"),
        json={"reason": "交接期", "impact": "邮件轮询暂停。"},
    )
    client.post(
        "/api/v1/admin/config-drafts",
        headers=owner,
        json={"key": "allow_public_registration", "value": "1"},
    )
    client.post(
        "/api/v1/admin/maintenance/windows",
        headers=step_up_headers(client, owner, "maintenance_schedule"),
        json={
            "title": "交接后维护",
            "notice": "预告。",
            "startsAt": (now + timedelta(days=1)).isoformat(timespec="seconds"),
            "endsAt": (now + timedelta(days=1, hours=1)).isoformat(timespec="seconds"),
        },
    )

    created = client.post("/api/v1/admin/handoff-summaries", headers=owner)
    assert created.status_code == 201, created.text
    payload = created.json()["payload"]
    open_items = payload["openItems"]
    assert any(item["id"] == ticket["id"] for item in open_items["tickets"])
    assert any(item["kind"] == "mail_imap" for item in open_items["taskPauses"])
    assert open_items["configDrafts"]
    assert open_items["maintenanceWindows"]
    assert payload["schemaVersion"] >= 303  # 本组迁移已应用
    assert "脱敏" in payload["redactionNote"]


def test_new380_export_requires_confirmation(ab_env):  # noqa: F811
    """未确认 → 409 handoff_not_confirmed；确认本身要 step-up。"""
    client = ab_env["client"]
    owner = ab_env["owner"]
    summary_id = client.post("/api/v1/admin/handoff-summaries", headers=owner).json()["summaryId"]

    bare_export = client.get(f"/api/v1/admin/handoff-summaries/{summary_id}/export", headers=owner)
    assert bare_export.status_code == 409
    assert bare_export.json()["error"]["type"] == "handoff_not_confirmed"

    bare_confirm = client.post(f"/api/v1/admin/handoff-summaries/{summary_id}/confirm", headers=owner)
    assert bare_confirm.status_code == 403
    assert bare_confirm.json()["error"]["type"] == "step_up_required"


def test_new380_confirm_then_export_stamps_once(ab_env):  # noqa: F811
    """step-up 确认 → 导出（含脱敏声明 + exportedAt）；重复确认 409。"""
    client = ab_env["client"]
    owner = ab_env["owner"]
    summary_id = client.post("/api/v1/admin/handoff-summaries", headers=owner).json()["summaryId"]

    confirmed = client.post(
        f"/api/v1/admin/handoff-summaries/{summary_id}/confirm",
        headers=step_up_headers(client, owner, "handoff_export"),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["confirmed"] is True

    export = client.get(f"/api/v1/admin/handoff-summaries/{summary_id}/export", headers=owner)
    assert export.status_code == 200, export.text
    payload = export.json()
    assert payload["exportedAt"]
    assert "脱敏" in payload["redactionNote"]

    re_confirm = client.post(
        f"/api/v1/admin/handoff-summaries/{summary_id}/confirm",
        headers=step_up_headers(client, owner, "handoff_export"),
    )
    assert re_confirm.status_code == 409


def test_new380_no_secret_values_in_payload(ab_env):  # noqa: F811
    """秘密清单只有状态位：payload 无任何 secret 值/密码形态。"""
    client = ab_env["client"]
    owner = ab_env["owner"]
    created = client.post("/api/v1/admin/handoff-summaries", headers=owner)
    text = created.text
    assert "secretsInventory" in text
    assert '"password"' not in text
    assert "sk-" not in text

    member = client.get("/api/v1/admin/handoff-summaries", headers=ab_env["b"])
    assert member.status_code == 403

    missing = client.get("/api/v1/admin/handoff-summaries/nope/export", headers=owner)
    assert missing.status_code == 404
