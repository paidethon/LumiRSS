"""NEW-296 邮件附件单独入库 — 转出独立条目 / 关系保留 / 隔离。"""

import base64

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.storage import Database
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册

_ATT_TEXT = "季度预算明细，共三行。\n第一行\n第二行"
_EML = (
    "Message-ID: <att296@example.test>\r\n"
    "From: a@example.test\r\n"
    "Subject: 带附件的邮件\r\n"
    'Content-Type: multipart/mixed; boundary="b296"\r\n'
    "MIME-Version: 1.0\r\n\r\n"
    "--b296\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n\r\n"
    "请查收附件。\r\n"
    "--b296\r\n"
    'Content-Type: text/plain; name="预算.txt"\r\n'
    'Content-Disposition: attachment; filename="预算.txt"\r\n'
    "Content-Transfer-Encoding: base64\r\n\r\n"
    f"{base64.b64encode(_ATT_TEXT.encode()).decode()}\r\n"
    "--b296--\r\n"
)


def _import_one(client: TestClient, mid: str = "<att296@example.test>") -> str:
    result = client.post(
        "/api/v1/email-materials/import",
        json={"files": [{"filename": "att.eml", "content": _EML.replace("<att296@example.test>", mid)}]},
    )
    assert result.status_code == 200, result.text
    return result.json()["imported"][0]["id"]


def test_new296_promote_creates_independent_item_with_relation():
    """转出 → 独立条目（可列表/下载），parent 关系保留，原邮件不动。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        material_id = _import_one(client)

        promoted = client.post(
            f"/api/v1/email-materials/{material_id}/attachments/0/promote"
        )
        assert promoted.status_code == 201, promoted.text
        item = promoted.json()
        assert item["filename"] == "预算.txt"
        assert item["materialId"] == material_id
        assert item["parentSubject"] == "带附件的邮件"
        assert item["size"] == len(_ATT_TEXT.encode())

        listing = client.get("/api/v1/email-attachment-items").json()
        assert listing["total"] if "total" in listing else len(listing["items"]) == 1

        download = client.get(
            f"/api/v1/email-attachment-items/{item['id']}/download"
        )
        assert download.status_code == 200, download.text
        assert download.content == _ATT_TEXT.encode()

        # 原邮件与附件清单不受影响（复制引用，不是移动）
        detail = client.get(f"/api/v1/email-materials/{material_id}").json()
        assert detail["attachments"][0]["filename"] == "预算.txt"

        # 删除附件条目 → 原邮件仍在
        deleted = client.delete(f"/api/v1/email-attachment-items/{item['id']}")
        assert deleted.status_code == 204
        assert (
            client.get(
                f"/api/v1/email-attachment-items/{item['id']}/download"
            ).status_code
            == 404
        )
        assert client.get(
            f"/api/v1/email-materials/{material_id}"
        ).status_code == 200


def test_new296_promote_validation_and_not_stored():
    """越界序号 404；未存内容的附件（只有元数据）422 不假装成功。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        material_id = _import_one(client)

        missing_ord = client.post(
            f"/api/v1/email-materials/{material_id}/attachments/9/promote"
        )
        assert missing_ord.status_code == 404

        # 单元级：stored=0（导入时超限只存元数据）→ 转出 422
        import asyncio

        async def seed_not_stored() -> None:
            await db.execute(
                "INSERT INTO email_attachment_blobs (id, material_id, ord,"
                " filename, content_type, size, sha256, stored, data, created_at)"
                " VALUES ('eab-x', ?, 5, '大文件.zip', 'application/zip',"
                " 99999999, 'deadbeef', 0, NULL, '2026-01-01T00:00:00Z')",
                (material_id,),
            )

        asyncio.run(seed_not_stored())
        not_stored = client.post(
            f"/api/v1/email-materials/{material_id}/attachments/5/promote"
        )
        assert not_stored.status_code == 422
        assert not_stored.json()["error"]["type"] == "attachment_not_stored"
        assert "未存内容" in not_stored.json()["error"]["message"]


def test_new296_cross_user_items_isolated(ab_env):  # noqa: F811
    """A 转出的附件条目对 B 不存在（per-user 库）。"""
    env = ab_env
    client = env["client"]
    result_a = client.post(
        "/api/v1/email-materials/import",
        json={"files": [{"filename": "att.eml", "content": _EML}]},
        headers=env["a"],
    )
    assert result_a.status_code == 200, result_a.text
    material_id = result_a.json()["imported"][0]["id"]

    promoted = client.post(
        f"/api/v1/email-materials/{material_id}/attachments/0/promote",
        headers=env["a"],
    )
    assert promoted.status_code == 201, promoted.text
    item_id = promoted.json()["id"]

    assert (
        client.get(
            f"/api/v1/email-attachment-items/{item_id}/download", headers=env["b"]
        ).status_code
        == 404
    )
    listing_b = client.get("/api/v1/email-attachment-items", headers=env["b"]).json()
    assert listing_b["items"] == []
    listing_a = client.get("/api/v1/email-attachment-items", headers=env["a"]).json()
    assert len(listing_a["items"]) == 1


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()
