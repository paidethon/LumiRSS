"""NEW-294 通讯订阅来源映射 — 精确地址匹配 / 导入自动归源 / 隔离。"""

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.storage import Database
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册


def _eml(from_addr: str, mid: str, subject: str = "周报") -> str:
    return (
        f"Message-ID: {mid}\r\n"
        f"From: {from_addr}\r\n"
        f"Subject: {subject}\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n\r\n正文。\r\n"
    )


def _upload(client: TestClient, from_addr: str, mid: str, **kw: str) -> dict:
    result = client.post(
        "/api/v1/email-materials/import",
        json={
            "files": [
                {"filename": f"{mid}.eml", "content": _eml(from_addr, mid, **kw)}
            ]
        },
    )
    assert result.status_code == 200, result.text
    return result.json()["imported"][0]


def test_new294_map_crd_and_validation():
    """设置/更新/删除映射；非法地址与空标签 422。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        put = client.put(
            "/api/v1/email-source-maps/news@letter.example",
            json={"sourceLabel": "订阅通讯"},
        )
        assert put.status_code == 200, put.text
        assert put.json()["fromAddr"] == "news@letter.example"

        # 更新同地址 = 覆盖
        updated = client.put(
            "/api/v1/email-source-maps/NEWS@letter.example",
            json={"sourceLabel": "改名的来源"},
        )
        assert updated.status_code == 200
        listing = client.get("/api/v1/email-source-maps").json()
        assert len(listing["items"]) == 1
        assert listing["items"][0]["sourceLabel"] == "改名的来源"

        bad_addr = client.put(
            "/api/v1/email-source-maps/not-an-address",
            json={"sourceLabel": "x"},
        )
        assert bad_addr.status_code == 422
        assert bad_addr.json()["error"]["type"] == "source_map_invalid"
        empty = client.put(
            "/api/v1/email-source-maps/a@b.example", json={"sourceLabel": "  "}
        )
        assert empty.status_code == 422

        deleted = client.delete("/api/v1/email-source-maps/news@letter.example")
        assert deleted.status_code == 204
        gone = client.delete("/api/v1/email-source-maps/news@letter.example")
        assert gone.status_code == 404


def test_new294_import_auto_assigns_and_view_filters():
    """映射后导入自动归源；?source= 过滤出该来源视图；未映射不归源。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        mapped = client.put(
            "/api/v1/email-source-maps/news@letter.example",
            json={"sourceLabel": "订阅通讯"},
        )
        assert mapped.status_code == 200

        in_source = _upload(client, "news@letter.example", "<s1@example.test>")
        unmapped = _upload(
            client, "other@example.test", "<s2@example.test>", subject="私人邮件"
        )
        assert in_source["sourceLabel"] == "订阅通讯"
        assert unmapped["sourceLabel"] == ""

        view = client.get(
            "/api/v1/email-materials", params={"source": "订阅通讯"}
        ).json()
        assert view["total"] == 1
        assert view["items"][0]["id"] == in_source["id"]
        everything = client.get("/api/v1/email-materials").json()
        assert everything["total"] == 2

        # 删除映射只影响之后的导入，不追溯改历史（诚实口径）
        client.delete("/api/v1/email-source-maps/news@letter.example")
        after = _upload(client, "news@letter.example", "<s3@example.test>")
        assert after["sourceLabel"] == ""
        kept = client.get(
            f"/api/v1/email-materials/{in_source['id']}"
        ).json()
        assert kept["sourceLabel"] == "订阅通讯"


def test_new294_cross_user_maps_isolated(ab_env):  # noqa: F811
    """A 的映射不影响 B 的导入归源（per-user 库）。"""
    env = ab_env
    client = env["client"]
    put = client.put(
        "/api/v1/email-source-maps/shared@example.test",
        json={"sourceLabel": "甲的来源"},
        headers=env["a"],
    )
    assert put.status_code == 200

    assert (
        client.get("/api/v1/email-source-maps", headers=env["b"]).json()["items"]
        == []
    )

    result_b = client.post(
        "/api/v1/email-materials/import",
        json={
            "files": [
                {
                    "filename": "b.eml",
                    "content": _eml("shared@example.test", "<iso-294@example.test>"),
                }
            ]
        },
        headers=env["b"],
    )
    assert result_b.status_code == 200, result_b.text
    assert result_b.json()["imported"][0]["sourceLabel"] == ""

    result_a = client.post(
        "/api/v1/email-materials/import",
        json={
            "files": [
                {
                    "filename": "a.eml",
                    "content": _eml("shared@example.test", "<iso-294a@example.test>"),
                }
            ]
        },
        headers=env["a"],
    )
    assert result_a.json()["imported"][0]["sourceLabel"] == "甲的来源"


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()
