"""NEW-300 邮件资料脱敏导出 — 默认脱敏 / 显式保留 / 删除清单 / 隔离。"""

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.new300_email_export import build_export_payload
from lumirss.storage import Database
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册

_EML = (
    "Message-ID: <exp300@example.test>\r\n"
    "Date: Tue, 29 Sep 2026 08:00:00 +0000\r\n"
    "From: 洪主任 <hong@corp.example>\r\n"
    "To: me@local.test\r\n"
    "Cc: legal@corp.example\r\n"
    "List-Unsubscribe: <https://corp.example/unsub>\r\n"
    "Subject: 含敏感信息的导出样本\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n\r\n"
    "正文包含地址 hong@corp.example 与结论。\r\n"
)

_FULL_HEADERS = (
    "Message-ID",
    "Date",
    "From",
    "To",
    "Cc",
    "List-Unsubscribe",
    "Subject",
    "MIME-Version",
)


def _import_one(client: TestClient) -> str:
    result = client.post(
        "/api/v1/email-materials/import",
        json={"files": [{"filename": "exp.eml", "content": _EML}]},
    )
    assert result.status_code == 200, result.text
    return result.json()["imported"][0]["id"]


def test_new300_default_export_is_redacted_with_removal_note():
    """默认（不勾选）：地址与完整头删除，removedFields 逐项说明。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        material_id = _import_one(client)

        exported = client.post(
            f"/api/v1/email-materials/{material_id}/export", json={}
        )
        assert exported.status_code == 200, exported.text
        payload = exported.json()
        assert payload["options"] == {
            "includeAddresses": False,
            "includeFullHeaders": False,
        }
        assert payload["from"] == ""
        assert payload["to"] == ""
        assert "hong@corp.example" not in payload["headers"].get("Cc", "")
        assert set(payload["headers"]) <= {"Message-ID", "Date"}
        fields = {r["field"] for r in payload["removedFields"]}
        assert "from" in fields and "headers" in fields
        assert any("未勾选保留地址" in r["reason"] for r in payload["removedFields"])
        assert "正文包含地址" in payload["bodyText"]  # 正文保留（未加遮罩）
        assert payload["subject"] == "含敏感信息的导出样本"

        # 原文仍私有保存：详情接口原样可读
        detail = client.get(f"/api/v1/email-materials/{material_id}").json()
        assert "hong@corp.example" in detail["bodyText"]
        assert len(detail["headers"]) == len(_FULL_HEADERS)


def test_new300_explicit_optin_and_mask_overlay():
    """显式勾选保留地址/完整头；遮罩叠加后正文占位 + maskedRegions。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        material_id = _import_one(client)
        made = client.post(
            f"/api/v1/email-materials/{material_id}/masks",
            json={"kind": "address", "value": "hong@corp.example"},
        )
        assert made.status_code == 201

        exported = client.post(
            f"/api/v1/email-materials/{material_id}/export",
            json={"includeAddresses": True, "includeFullHeaders": True},
        ).json()
        assert exported["from"] == "洪主任 <hong@corp.example>"
        assert exported["headers"]["Cc"] == "legal@corp.example"
        assert exported["headers"]["List-Unsubscribe"] == "<https://corp.example/unsub>"
        assert exported["removedFields"] == []
        # 遮罩叠加：正文里地址变占位符
        assert "hong@corp.example" not in exported["bodyText"]
        assert "[已隐藏·地址]" in exported["bodyText"]
        assert exported["maskedRegionCount"] == 1
        assert exported["maskedRegions"][0]["kindLabel"] == "地址"

        # 审计：选项与删除清单落库
        logs = client.get(
            "/api/v1/email-export-logs", params={"materialId": material_id}
        ).json()
        assert len(logs["items"]) == 1
        assert logs["items"][0]["options"]["includeAddresses"] is True


def test_new300_build_payload_unit_consistency():
    """单元：removedFields 声称删除的字段绝不出现在载荷里。"""
    material = {
        "subject": "s",
        "date": "d",
        "headers": {"From": "a@b.c", "To": "x@y.z", "Cc": "c@d.e", "X-Weird": "v"},
        "bodyText": "正文",
        "attachments": [],
        "tags": [],
    }
    payload, removed = build_export_payload(
        material, [], include_addresses=False, include_full_headers=False
    )
    assert payload["from"] == "" and payload["to"] == ""
    assert set(payload["headers"]) <= {"Message-ID", "Date"}
    assert all(r["field"] in ("from", "to", "headers", "headers.Cc") for r in removed)


def test_new300_cross_user_logs_isolated(ab_env):  # noqa: F811
    """A 的导出审计对 B 不可见；各自导出各自留痕。"""
    env = ab_env
    client = env["client"]

    def upload(who: dict[str, str]) -> str:
        result = client.post(
            "/api/v1/email-materials/import",
            json={"files": [{"filename": "e.eml", "content": _EML}]},
            headers=who,
        )
        assert result.status_code == 200, result.text
        return result.json()["imported"][0]["id"]

    a_id = upload(env["a"])
    upload(env["b"])

    exported = client.post(
        f"/api/v1/email-materials/{a_id}/export",
        json={"includeAddresses": True},
        headers=env["a"],
    )
    assert exported.status_code == 200, exported.text

    logs_b = client.get("/api/v1/email-export-logs", headers=env["b"]).json()
    assert logs_b["items"] == []
    logs_a = client.get("/api/v1/email-export-logs", headers=env["a"]).json()
    assert len(logs_a["items"]) == 1


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()
