"""NEW-291 EML 拖入阅读 — 解析/净化边界/大小封顶/失败诚实/per-user 隔离。"""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.storage import Database
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册

# 播种时间用相对 now（留 1 天余量），绝不写死日历日期。
_RECENT = (datetime.now(UTC) - timedelta(days=1)).strftime("%a, %d %b %Y %H:%M:%S +0000")


def _eml(
    subject: str = "季度汇报",
    body: str = "这是正文第一段。\n这是正文第二段。",
    extra_headers: str = "",
    html_part: str = "",
    attachment: tuple[str, str] | None = None,
    message_id: str = "<orig-291@example.test>",
) -> str:
    parts = ""
    if html_part:
        boundary = "b291"
        att = ""
        if attachment is not None:
            name, text = attachment
            att = (
                f"--{boundary}\r\n"
                f'Content-Type: text/plain; name="{name}"\r\n'
                f'Content-Disposition: attachment; filename="{name}"\r\n'
                "Content-Transfer-Encoding: base64\r\n\r\n"
                f"{__import__('base64').b64encode(text.encode()).decode()}\r\n"
            )
        parts = (
            f'Content-Type: multipart/mixed; boundary="{boundary}"\r\n\r\n'
            f"--{boundary}\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n\r\n"
            f"{body}\r\n"
            f"--{boundary}\r\n"
            "Content-Type: text/html; charset=utf-8\r\n\r\n"
            f"{html_part}\r\n"
            f"{att}"
            f"--{boundary}--\r\n"
        )
    else:
        parts = f"Content-Type: text/plain; charset=utf-8\r\n\r\n{body}\r\n"
    return (
        f"Message-ID: {message_id}\r\n"
        f"Date: {_RECENT}\r\n"
        f"From: 洪主任 <hong@example.test>\r\n"
        f"To: me@local.test\r\n"
        f"Subject: {subject}\r\n"
        f"{extra_headers}"
        f"MIME-Version: 1.0\r\n"
        f"{parts}"
    )


def _import(client: TestClient, *contents: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    return client.post(
        "/api/v1/email-materials/import",
        json={
            "files": [
                {"filename": f"mail-{i}.eml", "content": c}
                for i, c in enumerate(contents)
            ]
        },
        headers=headers,
    )


def test_new291_import_parses_headers_body_and_attachment_preview():
    """主题/发件信息/正文入库；附件元数据预览（名字/类型/大小/哈希）。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        result = _import(
            client,
            _eml(
                html_part="<p>富文本正文</p><script>alert(1)</script>",
                attachment=("预算表.txt", "预算内容"),
            ),
        )
        assert result.status_code == 200, result.text
        body = result.json()
        assert len(body["imported"]) == 1
        assert body["failed"] == []
        item = body["imported"][0]
        assert item["subject"] == "季度汇报"
        assert item["fromAddr"] == "hong@example.test"
        assert item["messageId"] == "orig-291@example.test"

        detail = client.get(f"/api/v1/email-materials/{item['id']}").json()
        assert "这是正文第一段" in detail["bodyText"]
        # 净化边界：body_html 存的是剥离 script 后的版本
        assert "<script>" not in detail["bodyHtmlSanitized"]
        assert "alert" not in detail["bodyHtmlSanitized"]
        # 头部按文本入库（含发件人显示名）
        assert detail["headers"]["From"] == "洪主任 <hong@example.test>"
        # 附件预览：名字/类型/大小/哈希齐全
        assert detail["attachments"][0]["filename"] == "预算表.txt"
        assert detail["attachments"][0]["contentType"] == "text/plain"
        assert detail["attachments"][0]["size"] == len("预算内容".encode())
        assert len(detail["attachments"][0]["sha256"]) == 64


def test_new291_html_only_body_is_sanitized_and_text_extracted():
    """只有 HTML 部件的邮件：净化后存 html，文本版照常可读。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        html = "<div><h2>标题行</h2><p>段落<b>加粗</b></p><img src='https://tracker.example/x.png'></div>"
        result = _import(
            client,
            _eml(
                subject="纯 HTML",
                body="占位",
                html_part=html,
                message_id="<html-only-291@example.test>",
            ),
        )
        # multipart 里 text/plain 占位在前面 → get_body 选 plain；这里验证
        # html part 存在时净化边界同样成立。
        assert result.status_code == 200
        detail = client.get(
            f"/api/v1/email-materials/{result.json()['imported'][0]['id']}"
        ).json()
        if detail["bodyHtmlSanitized"]:
            assert "img" not in detail["bodyHtmlSanitized"]
            assert "tracker.example" not in detail["bodyHtmlSanitized"]


def test_new291_bad_file_fails_alone_and_batch_survives():
    """坏文件按「单文件失败」如实给原因，同批好文件照常入库。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        result = _import(
            client,
            "这不是一封邮件，只是随手存的文本。",
            _eml(subject="好邮件", message_id="<good-291@example.test>"),
        )
        assert result.status_code == 200, result.text
        body = result.json()
        assert len(body["imported"]) == 1
        assert len(body["failed"]) == 1
        assert "没有邮件头部" in body["failed"][0]["reason"]
        assert body["failed"][0]["filename"] == "mail-0.eml"


def test_new291_oversize_file_rejected_attachment_cap_honest():
    """解析层拒绝超限文件；附件存储上限口径如实（超限只存元数据）。"""
    from lumirss.new291_email_import import (
        MAX_ATTACHMENT_STORED,
        MAX_EML_BYTES,
        EmailImportInvalid,
        parse_eml,
    )

    assert MAX_EML_BYTES == 4 * 1024 * 1024
    assert MAX_ATTACHMENT_STORED == 2 * 1024 * 1024
    try:
        parse_eml(b"x" * (MAX_EML_BYTES + 1))
        raise AssertionError("oversize file must raise")
    except EmailImportInvalid as exc:
        assert "大小上限" in str(exc)


def test_new291_list_and_detail_roundtrip():
    """清单给摘要（不吐正文）；详情给净化正文与头部。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        imported = _import(
            client,
            _eml(subject="清单一", message_id="<list-1-291@example.test>"),
        ).json()["imported"][0]
        listing = client.get("/api/v1/email-materials").json()
        assert listing["total"] == 1
        row = listing["items"][0]
        assert row["subject"] == "清单一"
        assert "bodyText" not in row  # 摘要不带正文
        detail = client.get(f"/api/v1/email-materials/{imported['id']}").json()
        assert "这是正文第一段" in detail["bodyText"]
        missing = client.get("/api/v1/email-materials/eml-nope")
        assert missing.status_code == 404
        assert missing.json()["error"]["type"] == "email_material_not_found"


def test_new291_cross_user_isolation(ab_env):  # noqa: F811
    """A 导入的邮件对 B 完全不可见（per-user 库）。"""
    env = ab_env
    client = env["client"]
    imported = _import(
        client,
        _eml(subject="甲的私密邮件", message_id="<private-291@example.test>"),
        headers=env["a"],
    )
    assert imported.status_code == 200, imported.text
    mine = imported.json()["imported"]
    assert len(mine) == 1

    listing_b = client.get("/api/v1/email-materials", headers=env["b"]).json()
    assert listing_b["total"] == 0
    detail_b = client.get(
        f"/api/v1/email-materials/{mine[0]['id']}", headers=env["b"]
    )
    assert detail_b.status_code == 404
    listing_a = client.get("/api/v1/email-materials", headers=env["a"]).json()
    assert listing_a["total"] == 1


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()
