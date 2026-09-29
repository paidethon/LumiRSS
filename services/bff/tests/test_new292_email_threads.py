"""NEW-292 邮件会话串联 — References 自动成串 / 手动关联 / 隔离。"""

from typing import Any

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.storage import Database
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册


def _eml(
    subject: str,
    message_id: str,
    *,
    in_reply_to: str = "",
    references: str = "",
    body: str = "会话正文。",
) -> str:
    headers = ""
    if in_reply_to:
        headers += f"In-Reply-To: {in_reply_to}\r\n"
    if references:
        headers += f"References: {references}\r\n"
    return (
        f"Message-ID: {message_id}\r\n"
        f"From: a@example.test\r\n"
        f"Subject: {subject}\r\n"
        f"{headers}"
        f"Content-Type: text/plain; charset=utf-8\r\n\r\n{body}\r\n"
    )


def _import(client: TestClient, *pairs: tuple[str, str]) -> list[dict[str, Any]]:
    result = client.post(
        "/api/v1/email-materials/import",
        json={
            "files": [
                {"filename": f"{mid}.eml", "content": _eml(subject, mid)}
                for subject, mid in pairs
            ]
        },
    )
    assert result.status_code == 200, result.text
    return result.json()["imported"]


def test_new292_references_chain_threads_automatically():
    """A→B→C 按真实 In-Reply-To/References 归入同一会话（references）；
    无引用的干扰邮件不入串。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        first = _import(client, ("开场", "<t1@example.test>"))[0]
        noise = _import(client, ("闲聊", "<noise@example.test>"))[0]
        reply = client.post(
            "/api/v1/email-materials/import",
            json={
                "files": [
                    {
                        "filename": "reply.eml",
                        "content": _eml(
                            "Re: 开场",
                            "<t2@example.test>",
                            in_reply_to="<t1@example.test>",
                            references="<t1@example.test>",
                        ),
                    }
                ]
            },
        ).json()["imported"][0]
        third = client.post(
            "/api/v1/email-materials/import",
            json={
                "files": [
                    {
                        "filename": "reply2.eml",
                        "content": _eml(
                            "Re: Re: 开场",
                            "<t3@example.test>",
                            in_reply_to="<t2@example.test>",
                            references="<t1@example.test> <t2@example.test>",
                        ),
                    }
                ]
            },
        ).json()["imported"][0]

        noise_detail = client.get(
            f"/api/v1/email-materials/{noise['id']}"
        ).json()
        assert noise_detail["threadId"] == ""
        assert noise_detail["linkMode"] == "none"

        thread_id = client.get(
            f"/api/v1/email-materials/{reply['id']}"
        ).json()["threadId"]
        assert thread_id
        for member_id in (first["id"], reply["id"], third["id"]):
            member = client.get(
                f"/api/v1/email-materials/{member_id}"
            ).json()
            assert member["threadId"] == thread_id
            assert member["linkMode"] == "references"

        view = client.get(f"/api/v1/email-threads/{thread_id}").json()
        assert {m["id"] for m in view["members"]} == {
            first["id"],
            reply["id"],
            third["id"],
        }
        assert "真实头部字段" in view["honestyNote"]


def test_new292_manual_link_creates_and_joins_threads():
    """字段不足：手动关联新建会话；第三封再手动并入同一会话。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        imported = _import(
            client,
            ("询价", "<m1@example.test>"),
            ("报价", "<m2@example.test>"),
            ("还价", "<m3@example.test>"),
        )
        m1, m2, m3 = imported
        # m1/m2 都无会话 → 手动关联新建一个
        linked = client.post(
            f"/api/v1/email-materials/{m2['id']}/thread-link",
            json={"targetId": m1["id"]},
        )
        assert linked.status_code == 200, linked.text
        view = linked.json()
        assert len(view["members"]) == 2
        modes = {m["id"]: m["linkMode"] for m in view["members"]}
        assert modes[m1["id"]] == "manual"
        assert modes[m2["id"]] == "manual"
        thread_id = view["threadId"]

        # m3 手动并入同一会话
        again = client.post(
            f"/api/v1/email-materials/{m3['id']}/thread-link",
            json={"targetId": m1["id"]},
        )
        assert again.status_code == 200
        assert len(again.json()["members"]) == 3

        fetched = client.get(f"/api/v1/email-threads/{thread_id}").json()
        assert {m["id"] for m in fetched["members"]} == {m1["id"], m2["id"], m3["id"]}


def test_new292_manual_link_validation():
    """自关联 422；目标不存在 404；会话不存在 404。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        (m1,) = _import(client, ("唯一", "<v1@example.test>"))

        self_link = client.post(
            f"/api/v1/email-materials/{m1['id']}/thread-link",
            json={"targetId": m1["id"]},
        )
        assert self_link.status_code == 422
        assert self_link.json()["error"]["type"] == "thread_link_invalid"

        missing = client.post(
            f"/api/v1/email-materials/{m1['id']}/thread-link",
            json={"targetId": "eml-nope"},
        )
        assert missing.status_code == 404

        no_thread = client.get("/api/v1/email-threads/eth-nope")
        assert no_thread.status_code == 404
        assert no_thread.json()["error"]["type"] == "email_thread_not_found"


def test_new292_cross_user_threads_isolated(ab_env):  # noqa: F811
    """A 的会话与手动关联对 B 不存在（per-user 库）。"""
    env = ab_env
    client = env["client"]

    def upload(mid: str, subject: str, who: dict[str, str]) -> dict[str, Any]:
        result = client.post(
            "/api/v1/email-materials/import",
            json={
                "files": [
                    {"filename": f"{mid}.eml", "content": _eml(subject, mid)}
                ]
            },
            headers=who,
        )
        assert result.status_code == 200, result.text
        return result.json()["imported"][0]

    a1 = upload("<iso-a1@example.test>", "甲一", env["a"])
    a2 = upload("<iso-a2@example.test>", "甲二", env["a"])
    b1 = upload("<iso-b1@example.test>", "乙一", env["b"])

    linked = client.post(
        f"/api/v1/email-materials/{a1['id']}/thread-link",
        json={"targetId": a2["id"]},
        headers=env["a"],
    )
    assert linked.status_code == 200, linked.text
    thread_id = linked.json()["threadId"]

    # B：自己的条目不在 A 的会话里，也看不见 A 的会话
    assert client.get(f"/api/v1/email-threads/{thread_id}", headers=env["b"]).status_code == 404
    b_view = client.get(f"/api/v1/email-materials/{b1['id']}", headers=env["b"]).json()
    assert b_view["threadId"] == ""
    # A 侧会话仍完好
    a_view = client.get(f"/api/v1/email-threads/{thread_id}", headers=env["a"]).json()
    assert {m["id"] for m in a_view["members"]} == {a1["id"], a2["id"]}


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()
