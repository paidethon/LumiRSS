"""NEW-297 邮件导入规则预览 — 预览/导入同路径 / 规则校验 / 隔离。"""

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.storage import Database
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册

_EML_TEMPLATE = (
    "Message-ID: <{mid}>\r\n"
    "From: {addr}\r\n"
    "Subject: {subject}\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n\r\n正文。\r\n"
)

RULES = [
    {"kind": "subject_clean", "config": {"pattern": r"^\[外部\]\s*", "replacement": ""}},
    {"kind": "tag", "config": {"value": "邮件批次A"}},
    {
        "kind": "source_map",
        "config": {"fromAddr": "news@letter.example", "sourceLabel": "本批通讯"},
    },
]


def _file(mid: str, subject: str, addr: str = "news@letter.example") -> dict:
    return {
        "filename": f"{mid}.eml",
        "content": _EML_TEMPLATE.format(
            mid=mid, subject=subject, addr=addr
        ),
    }


def test_new297_malformed_message_id_does_not_crash_import():
    """畸形 Message-ID（<<a@b>>）：解析层不炸，ID 归一化后仍可用。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        content = _EML_TEMPLATE.format(
            mid="<double-wrapped@example.test>",
            subject="畸形ID",
            addr="news@letter.example",
        ).replace(
            "Message-ID: <<double-wrapped@example.test>>",
            "Message-ID: <<double-wrapped@example.test>> extra",
        )
        result = client.post(
            "/api/v1/email-materials/import",
            json={"files": [{"filename": "weird.eml", "content": content}]},
        )
        assert result.status_code == 200, result.text
        assert len(result.json()["imported"]) == 1


def test_new297_preview_applies_rules_without_writing():
    """预览：主题清理/标签/本批来源映射如实展示；零写入。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        preview = client.post(
            "/api/v1/email-imports/preview",
            json={
                "files": [_file("p1@example.test", "[外部] 周报一")],
                "rules": RULES,
            },
        )
        assert preview.status_code == 200, preview.text
        sample = preview.json()["samples"][0]
        assert sample["status"] == "ok"
        assert sample["subjectRaw"] == "[外部] 周报一"
        assert sample["subject"] == "周报一"
        assert sample["tags"] == ["邮件批次A"]
        assert sample["sourceLabel"] == "本批通讯"
        assert sample["sourceOrigin"] == "batch-rule"

        # 零写入：清单仍为空
        listing = client.get("/api/v1/email-materials").json()
        assert listing["total"] == 0


def test_new297_confirm_applies_same_rules_to_batch():
    """确认后导入：与预览同一变换路径——主题/标签/来源一致落库。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        imported = client.post(
            "/api/v1/email-materials/import",
            json={"files": [_file("c1@example.test", "[外部] 周报二")], "rules": RULES},
        )
        assert imported.status_code == 200, imported.text
        item = imported.json()["imported"][0]
        assert item["subject"] == "周报二"
        assert item["tags"] == ["邮件批次A"]
        assert item["sourceLabel"] == "本批通讯"
        assert item["sourceOrigin"] == "batch-rule"

        detail = client.get(f"/api/v1/email-materials/{item['id']}").json()
        assert detail["subject"] == "周报二"
        assert detail["tags"] == ["邮件批次A"]
        assert detail["sourceLabel"] == "本批通讯"

        # 无规则导入不受影响（清理由规则驱动，不是全局行为）
        plain = client.post(
            "/api/v1/email-materials/import",
            json={"files": [_file("c2@example.test", "[外部] 未清理")]},
        ).json()["imported"][0]
        assert plain["subject"] == "[外部] 未清理"


def test_new297_rule_validation_and_persisted_origin():
    """坏正则 422（不静默跳过）；持久映射（NEW-294）标 persisted，
    本批规则覆盖为 batch-rule；规则可保存/列出/删除。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        bad = client.post(
            "/api/v1/email-imports/preview",
            json={
                "files": [_file("v1@example.test", "标题")],
                "rules": [{"kind": "subject_clean", "config": {"pattern": "(["}}],
            },
        )
        assert bad.status_code == 422
        assert bad.json()["error"]["type"] == "import_rule_invalid"

        # 持久映射落底
        persisted = client.put(
            "/api/v1/email-source-maps/news@letter.example",
            json={"sourceLabel": "持久来源"},
        )
        assert persisted.status_code == 200
        sample = client.post(
            "/api/v1/email-imports/preview",
            json={"files": [_file("v2@example.test", "标题")], "rules": []},
        ).json()["samples"][0]
        assert sample["sourceLabel"] == "持久来源"
        assert sample["sourceOrigin"] == "persisted"
        # 本批规则覆盖
        overridden = client.post(
            "/api/v1/email-imports/preview",
            json={
                "files": [_file("v3@example.test", "标题")],
                "rules": [RULES[2]],
            },
        ).json()["samples"][0]
        assert overridden["sourceLabel"] == "本批通讯"
        assert overridden["sourceOrigin"] == "batch-rule"

        saved = client.post(
            "/api/v1/email-import-rules",
            json=RULES[0],
        )
        assert saved.status_code == 201, saved.text
        rule_id = saved.json()["id"]
        listed = client.get("/api/v1/email-import-rules").json()
        assert listed["items"][0]["id"] == rule_id
        deleted = client.delete(f"/api/v1/email-import-rules/{rule_id}")
        assert deleted.status_code == 204


def test_new297_cross_user_rules_isolated(ab_env):  # noqa: F811
    """A 保存的规则对 B 不存在；B 不传规则时清理不会发生。"""
    env = ab_env
    client = env["client"]
    saved = client.post(
        "/api/v1/email-import-rules",
        json=RULES[0],
        headers=env["a"],
    )
    assert saved.status_code == 201
    listed_b = client.get("/api/v1/email-import-rules", headers=env["b"]).json()
    assert listed_b["items"] == []

    result_b = client.post(
        "/api/v1/email-materials/import",
        json={"files": [_file("iso-297@example.test", "[外部] 乙的邮件")]},
        headers=env["b"],
    )
    assert result_b.status_code == 200, result_b.text
    item_b = result_b.json()["imported"][0]
    # B 没传规则、A 保存的规则也不属于 B：主题清理不发生
    assert item_b["subject"] == "[外部] 乙的邮件"
    assert item_b["sourceLabel"] == ""


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()
