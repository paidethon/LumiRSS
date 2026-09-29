"""NEW-299 通讯退订信息卡 — 头部解析 / 无信息诚实 / 打开仅审计 / 隔离。"""

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.new299_email_unsubscribe import parse_unsubscribe_headers
from lumirss.storage import Database
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册

_UNSUB_EML = (
    "Message-ID: <unsub299@example.test>\r\n"
    "From: newsletter@corp.example\r\n"
    "Subject: 订阅通讯\r\n"
    "List-Unsubscribe: <https://corp.example/unsub?u=abc>, <mailto:unsub@corp.example>\r\n"
    "List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n"
    "List-Help: <https://corp.example/help>\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n\r\n通讯内容。\r\n"
)

_PLAIN_EML = (
    "Message-ID: <plain299@example.test>\r\n"
    "From: friend@example.test\r\n"
    "Subject: 无退订头的邮件\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n\r\n私人邮件。\r\n"
)


def _upload(client: TestClient, content: str, filename: str) -> str:
    result = client.post(
        "/api/v1/email-materials/import",
        json={"files": [{"filename": filename, "content": content}]},
    )
    assert result.status_code == 200, result.text
    return result.json()["imported"][0]["id"]


def test_new299_parse_unsubscribe_headers_unit():
    """单元：<http> 与 <mailto> 项分开识别；垃圾项忽略。"""
    methods = parse_unsubscribe_headers(
        {
            "List-Unsubscribe": (
                "<https://a.example/u>, <mailto:u@a.example>, junk-item"
            )
        }
    )
    assert methods == [
        {"type": "http", "target": "https://a.example/u"},
        {"type": "mailto", "target": "mailto:u@a.example"},
    ]


def test_new299_card_shows_methods_and_records_open():
    """信息卡如实展示头部提供的途径与 One-Click 声明；打开仅记录。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        material_id = _upload(client, _UNSUB_EML, "unsub.eml")

        card = client.get(
            f"/api/v1/email-materials/{material_id}/unsubscribe"
        ).json()
        assert card["available"] is True
        assert card["oneClickDeclared"] is True
        assert card["listHelp"] == "https://corp.example/help"
        types = {m["type"] for m in card["methods"]}
        assert types == {"http", "mailto"}
        assert "绝不自动执行退订请求" in card["honestyNote"]
        assert card["opens"] == []

        opened = client.post(
            f"/api/v1/email-materials/{material_id}/unsubscribe-open",
            json={"method": "http", "target": "https://corp.example/unsub?u=abc"},
        )
        assert opened.status_code == 201, opened.text
        assert "不发送" in opened.json()["note"]

        card_again = client.get(
            f"/api/v1/email-materials/{material_id}/unsubscribe"
        ).json()
        assert len(card_again["opens"]) == 1
        assert card_again["opens"][0]["method"] == "http"

        # 打开不在原文信息里的途径 → 422（不假装可打开）
        bogus = client.post(
            f"/api/v1/email-materials/{material_id}/unsubscribe-open",
            json={"method": "http", "target": "https://evil.example/unsub"},
        )
        assert bogus.status_code == 422
        assert bogus.json()["error"]["type"] == "unsub_open_invalid"


def test_new299_no_info_is_honest_404_semantics():
    """头部没有退订信息：available=false + 明确说明，不生成猜测地址。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        material_id = _upload(client, _PLAIN_EML, "plain.eml")
        card = client.get(
            f"/api/v1/email-materials/{material_id}/unsubscribe"
        ).json()
        assert card["available"] is False
        assert card["methods"] == []
        assert card["oneClickDeclared"] is False
        assert "不会猜测退订地址" in card["honestyNote"]

        opened = client.post(
            f"/api/v1/email-materials/{material_id}/unsubscribe-open",
            json={"method": "http", "target": "https://x.example"},
        )
        assert opened.status_code == 422

        missing = client.get("/api/v1/email-materials/eml-nope/unsubscribe")
        assert missing.status_code == 404


def test_new299_cross_user_opens_isolated(ab_env):  # noqa: F811
    """A 的打开记录对 B 不可见（per-user 库）。"""
    env = ab_env
    client = env["client"]

    def upload(who: dict[str, str]) -> str:
        result = client.post(
            "/api/v1/email-materials/import",
            json={"files": [{"filename": "u.eml", "content": _UNSUB_EML}]},
            headers=who,
        )
        assert result.status_code == 200, result.text
        return result.json()["imported"][0]["id"]

    a_id = upload(env["a"])
    b_id = upload(env["b"])
    opened = client.post(
        f"/api/v1/email-materials/{a_id}/unsubscribe-open",
        json={"method": "mailto", "target": "mailto:unsub@corp.example"},
        headers=env["a"],
    )
    assert opened.status_code == 201, opened.text

    card_b = client.get(
        f"/api/v1/email-materials/{b_id}/unsubscribe", headers=env["b"]
    ).json()
    assert card_b["opens"] == []
    card_a = client.get(
        f"/api/v1/email-materials/{a_id}/unsubscribe", headers=env["a"]
    ).json()
    assert len(card_a["opens"]) == 1


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()
