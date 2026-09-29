"""NEW-295 邮件隐私内容遮罩 — 字面遮罩 / 分享视图 / 原文私有 / 隔离。"""

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.new295_email_masks import apply_masks
from lumirss.storage import Database
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册

_BODY = (
    "收件人：洪主任 <hong@example.test>\n"
    "正文第一段，谈具体事情。\n"
    "此致\n敬礼\n张三 · 财务部 · 13800138000"
)


def _import_one(client: TestClient, body: str = _BODY, mid: str = "<mk295@example.test>") -> str:
    eml = (
        f"Message-ID: {mid}\r\nFrom: a@example.test\r\nSubject: 遮罩样本\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n\r\n{body}\r\n"
    )
    result = client.post(
        "/api/v1/email-materials/import",
        json={"files": [{"filename": "mask.eml", "content": eml}]},
    )
    assert result.status_code == 200, result.text
    return result.json()["imported"][0]["id"]


def test_new295_mask_literal_text_and_share_view():
    """地址/签名/自选文字三 kinds 全部按字面遮住；分享视图给占位符。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        material_id = _import_one(client)
        for kind, value in (
            ("address", "洪主任 <hong@example.test>"),
            ("signature", "张三 · 财务部 · 13800138000"),
            ("custom", "谈具体事情"),
        ):
            made = client.post(
                f"/api/v1/email-materials/{material_id}/masks",
                json={"kind": kind, "value": value},
            )
            assert made.status_code == 201, made.text

        view = client.get(
            f"/api/v1/email-materials/{material_id}/share-view"
        ).json()
        masked = view["maskedBodyText"]
        assert "hong@example.test" not in masked
        assert "13800138000" not in masked
        assert "谈具体事情" not in masked
        assert "[已隐藏·地址]" in masked
        assert "[已隐藏·签名]" in masked
        assert "[已隐藏·选中文字]" in masked
        assert view["originalPrivate"] is True
        assert "不会自动识别" in view["honestyNote"]
        assert len(view["masks"]) == 3

        # 原文仍私有保存：详情接口原样返回
        detail = client.get(f"/api/v1/email-materials/{material_id}").json()
        assert "hong@example.test" in detail["bodyText"]
        assert "13800138000" in detail["bodyText"]


def test_new295_validation_text_must_exist_and_delete():
    """不在正文里的文本 422（不假装遮了不存在的内容）；删除遮罩恢复。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        material_id = _import_one(client)

        absent = client.post(
            f"/api/v1/email-materials/{material_id}/masks",
            json={"kind": "custom", "value": "正文里没有这句话"},
        )
        assert absent.status_code == 422
        assert absent.json()["error"]["type"] == "mask_text_not_found"

        bad_kind = client.post(
            f"/api/v1/email-materials/{material_id}/masks",
            json={"kind": "magic", "value": "正文"},
        )
        assert bad_kind.status_code == 422

        made = client.post(
            f"/api/v1/email-materials/{material_id}/masks",
            json={"kind": "address", "value": "hong@example.test"},
        ).json()
        view_before = client.get(
            f"/api/v1/email-materials/{material_id}/share-view"
        ).json()
        assert "hong@example.test" not in view_before["maskedBodyText"]

        removed = client.delete(f"/api/v1/email-masks/{made['id']}")
        assert removed.status_code == 204
        view_after = client.get(
            f"/api/v1/email-materials/{material_id}/share-view"
        ).json()
        assert "hong@example.test" in view_after["maskedBodyText"]

        gone = client.delete(f"/api/v1/email-masks/{made['id']}")
        assert gone.status_code == 404


def test_new295_apply_masks_unit_overlapping():
    """单元：多条遮罩按序应用；互相重叠时先到先得，不二次替换占位符。"""
    masks = [
        {"kind": "address", "value": "a@example.test"},
        {"kind": "custom", "value": "[已隐藏·地址]"},  # 恶意/误操作：遮占位符
    ]
    assert apply_masks("写給 a@example.test 的人", masks) == (
        "写給 [已隐藏·地址] 的人"
    )


def test_new295_cross_user_masks_isolated(ab_env):  # noqa: F811
    """A 的遮罩不影响 B 的分享视图（per-user 库）。"""
    env = ab_env
    client = env["client"]

    def upload(who: dict[str, str]) -> str:
        eml = (
            "Message-ID: <iso-mk@example.test>\r\nFrom: a@example.test\r\n"
            "Subject: 各自导入\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
            "秘密是 13800138000。\r\n"
        )
        result = client.post(
            "/api/v1/email-materials/import",
            json={"files": [{"filename": "m.eml", "content": eml}]},
            headers=who,
        )
        assert result.status_code == 200, result.text
        return result.json()["imported"][0]["id"]

    a_id = upload(env["a"])
    b_id = upload(env["b"])
    made = client.post(
        f"/api/v1/email-materials/{a_id}/masks",
        json={"kind": "custom", "value": "13800138000"},
        headers=env["a"],
    )
    assert made.status_code == 201, made.text

    share_b = client.get(
        f"/api/v1/email-materials/{b_id}/share-view", headers=env["b"]
    ).json()
    assert "13800138000" in share_b["maskedBodyText"]
    assert share_b["masks"] == []
    share_a = client.get(
        f"/api/v1/email-materials/{a_id}/share-view", headers=env["a"]
    ).json()
    assert "13800138000" not in share_a["maskedBodyText"]


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()
