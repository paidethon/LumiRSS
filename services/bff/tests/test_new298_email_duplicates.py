"""NEW-298 邮件重复识别复核 — 跳过/冲突分流 / 三种保留选择 / 隔离。"""

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.storage import Database
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册


def _eml(mid: str, body: str, subject: str = "重复样本") -> str:
    return (
        f"Message-ID: {mid}\r\n"
        f"From: a@example.test\r\n"
        f"Subject: {subject}\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n\r\n{body}\r\n"
    )


def _import(client: TestClient, mid: str, body: str, **kw: str) -> dict:
    result = client.post(
        "/api/v1/email-materials/import",
        json={
            "files": [
                {"filename": f"{mid}.eml", "content": _eml(mid, body, **kw)}
            ]
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def test_new298_identical_duplicate_skipped_conflicting_queued():
    """同 ID 同正文 → skipped；同 ID 不同正文 → 冲突队列（不静默写入）。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        first = _import(client, "<dup@example.test>", "原始正文")
        assert len(first["imported"]) == 1

        same = _import(client, "<dup@example.test>", "原始正文")
        assert same["imported"] == []
        assert len(same["skipped"]) == 1
        assert "正文一致" in same["skipped"][0]["reason"]

        diff = _import(client, "<dup@example.test>", "被修改过的正文，不一样")
        assert diff["imported"] == []
        assert len(diff["conflicts"]) == 1
        conflict = diff["conflicts"][0]
        assert conflict["existingId"] == first["imported"][0]["id"]

        # 冲突条目未入库：清单里只有原版一条
        listing = client.get("/api/v1/email-materials").json()
        assert listing["total"] == 1

        queue = client.get("/api/v1/email-duplicates").json()
        assert queue["items"][0]["id"] == conflict["conflictId"]
        assert queue["items"][0]["status"] == "pending"
        assert queue["items"][0]["digestsDiffer"] is True
        assert queue["items"][0]["incomingPreview"]["subject"] == "重复样本"


def test_new298_resolve_choices_keep_versions():
    """三种选择：保留原版丢弃来件 / 保留来件新增 / 两个都留。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        _first = _import(client, "<r1@example.test>", "甲版本")["imported"][0]
        conflict = _import(client, "<r1@example.test>", "乙版本，不同")["conflicts"][0][
            "conflictId"
        ]

        # 无效选择 422
        bad = client.post(
            f"/api/v1/email-duplicates/{conflict}/resolve",
            json={"choice": "overwrite"},
        )
        assert bad.status_code == 422
        assert bad.json()["error"]["type"] == "conflict_choice_invalid"

        kept_existing = client.post(
            f"/api/v1/email-duplicates/{conflict}/resolve",
            json={"choice": "keep_existing"},
        ).json()
        assert kept_existing["status"] == "kept_existing"
        assert kept_existing["resultId"] == ""
        assert client.get("/api/v1/email-materials").json()["total"] == 1

        # 已复核的冲突再复核 → 404
        again = client.post(
            f"/api/v1/email-duplicates/{conflict}/resolve",
            json={"choice": "keep_both"},
        )
        assert again.status_code == 404

        # 新冲突 → keep_incoming：来件成为独立条目
        conflict2 = _import(client, "<r1@example.test>", "丙版本，又一个")[
            "conflicts"
        ][0]["conflictId"]
        kept_incoming = client.post(
            f"/api/v1/email-duplicates/{conflict2}/resolve",
            json={"choice": "keep_incoming"},
        ).json()
        assert kept_incoming["status"] == "kept_incoming"
        assert kept_incoming["resultId"]
        detail = client.get(
            f"/api/v1/email-materials/{kept_incoming['resultId']}"
        ).json()
        assert "丙版本" in detail["bodyText"]
        assert detail["importKind"] == "duplicate-incoming"

        # 新冲突 → keep_both：两个版本都在
        conflict3 = _import(client, "<r1@example.test>", "丁版本")["conflicts"][0][
            "conflictId"
        ]
        kept_both = client.post(
            f"/api/v1/email-duplicates/{conflict3}/resolve",
            json={"choice": "keep_both"},
        ).json()
        assert kept_both["status"] == "kept_both"
        # 甲（原版）+ 丙（keep_incoming）+ 丁（keep_both）= 3 条
        assert client.get("/api/v1/email-materials").json()["total"] == 3
        # 保留来件时附件关系完好（该样本无附件，验证条目可读即可）


def test_new298_conflict_keeps_attachment_bytes_on_keep_incoming():
    """来件带附件时，复核保留来件 → 附件字节一并恢复（不丢内容）。"""
    import base64

    att = base64.b64encode("冲突来件附件".encode()).decode()
    eml = (
        "Message-ID: <att-dup@example.test>\r\n"
        "From: a@example.test\r\n"
        "Subject: 带附件冲突\r\n"
        'Content-Type: multipart/mixed; boundary="bd"\r\n'
        "MIME-Version: 1.0\r\n\r\n"
        "--bd\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n版本A正文\r\n"
        "--bd\r\n"
        'Content-Type: text/plain; name="a.txt"\r\n'
        'Content-Disposition: attachment; filename="a.txt"\r\n'
        f"Content-Transfer-Encoding: base64\r\n\r\n{att}\r\n"
        "--bd--\r\n"
    )
    eml_b = eml.replace("版本A正文", "版本B正文，不同")
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        first = client.post(
            "/api/v1/email-materials/import",
            json={"files": [{"filename": "a.eml", "content": eml}]},
        ).json()["imported"][0]
        conflict = client.post(
            "/api/v1/email-materials/import",
            json={"files": [{"filename": "b.eml", "content": eml_b}]},
        ).json()["conflicts"][0]["conflictId"]
        resolved = client.post(
            f"/api/v1/email-duplicates/{conflict}/resolve",
            json={"choice": "keep_incoming"},
        ).json()
        incoming_id = resolved["resultId"]
        detail = client.get(f"/api/v1/email-materials/{incoming_id}").json()
        assert "版本B正文" in detail["bodyText"]
        blob = client.post(
            f"/api/v1/email-materials/{incoming_id}/attachments/0/promote"
        )
        assert blob.status_code == 201, blob.text
        download = client.get(
            f"/api/v1/email-attachment-items/{blob.json()['id']}/download"
        )
        assert download.content == "冲突来件附件".encode()
        _ = first  # 原版不受影响


def test_new298_cross_user_conflicts_isolated(ab_env):  # noqa: F811
    """A 的冲突队列对 B 不存在；解决结果互不可见。"""
    env = ab_env
    client = env["client"]

    def upload(who: dict[str, str], body: str, mid: str) -> dict:
        result = client.post(
            "/api/v1/email-materials/import",
            json={
                "files": [{"filename": "d.eml", "content": _eml(mid, body)}]
            },
            headers=who,
        )
        assert result.status_code == 200, result.text
        return result.json()

    upload(env["a"], "甲的原版", "<iso-dup@example.test>")
    conflict = upload(env["a"], "甲的来件版本", "<iso-dup@example.test>")[
        "conflicts"
    ][0]["conflictId"]

    assert client.get("/api/v1/email-duplicates", headers=env["b"]).json()["items"] == []
    resolve_b = client.post(
        f"/api/v1/email-duplicates/{conflict}/resolve",
        json={"choice": "keep_existing"},
        headers=env["b"],
    )
    assert resolve_b.status_code == 404
    resolve_a = client.post(
        f"/api/v1/email-duplicates/{conflict}/resolve",
        json={"choice": "keep_incoming"},
        headers=env["a"],
    )
    assert resolve_a.status_code == 200, resolve_a.text
    assert resolve_a.json()["resultId"]


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()
