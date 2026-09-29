"""NEW-279 问答结论采纳 — 移入笔记带 AI 标记 / 可改写 / 不覆盖人工修改。"""

from contextlib import contextmanager

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.storage import Database
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册


@contextmanager
def _client(db):
    with TestClient(app) as client:
        app.state.db = db
        yield client


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()


def _adopt(client, headers=None, **overrides):
    payload = {
        "conclusion": "文章的核心结论：温度升高会加快反应速率。",
        "citations": [{"index": 1, "entryRef": "e1.abc"}],
        "model": "model-a",
        "newTitle": "阅读结论",
    }
    payload.update(overrides)
    return client.post(
        "/api/v1/ai/answer-adoptions", json=payload, headers=headers
    )


def test_new279_adopt_note_carries_ai_marker():
    """采纳 → 新笔记带「来源：AI」标记与引用；改写保留标记。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with _client(db) as client:
        adoption = _adopt(client)
        assert adoption.status_code == 201, adoption.text
        body = adoption.json()
        note = client.get(f"/api/v1/library/notes/{body['noteUuid']}")
        assert note.status_code == 200
        content = note.json()["contentMd"]
        assert "来源：AI（model-a）" in content
        assert "温度升高会加快反应速率" in content
        assert "e1.abc" in content

        # 可改写：结论更新，AI 标记保留
        revised = client.patch(
            f"/api/v1/ai/answer-adoptions/{body['id']}",
            json={"conclusion": "改写后的结论：速率随温度指数增长。"},
        )
        assert revised.status_code == 200, revised.text
        content_after = client.get(
            f"/api/v1/library/notes/{body['noteUuid']}"
        ).json()["contentMd"]
        assert "改写后的结论" in content_after
        assert "来源：AI（model-a）" in content_after  # 标记永不摘除
        assert "温度升高会加快反应速率" not in content_after  # 旧结论被替换
        listing = client.get("/api/v1/ai/answer-adoptions").json()
        assert listing["total"] == 1


def test_new279_revise_conflicts_with_manual_edit():
    """笔记被直接编辑后改写 → 409 note_diverged（附现状，不静默覆盖）。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with _client(db) as client:
        body = _adopt(client).json()
        note_uuid = body["noteUuid"]
        # 用户直接改笔记（人工修改神圣）
        manual = client.patch(
            f"/api/v1/library/notes/{note_uuid}",
            json={"contentMd": "我手动重写的全部内容。"},
        )
        assert manual.status_code == 200, manual.text

        diverged = client.patch(
            f"/api/v1/ai/answer-adoptions/{body['id']}",
            json={"conclusion": "迟到的 AI 改写。"},
        )
        assert diverged.status_code == 409, diverged.text
        error = diverged.json()["error"]
        assert error["type"] == "note_diverged"
        assert error["noteContentMd"] == "我手动重写的全部内容。"
        # 笔记内容未被 AI 改写破坏
        assert (
            client.get(f"/api/v1/library/notes/{note_uuid}").json()["contentMd"]
            == "我手动重写的全部内容。"
        )


def test_new279_adopt_into_existing_note_and_delete_adoption():
    """采纳进既有笔记是追加；删除采纳只删台账，笔记内容不动。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with _client(db) as client:
        note = client.post(
            "/api/v1/library/notes",
            json={"title": "我的笔记", "contentMd": "原始内容\n"},
        )
        assert note.status_code == 201, note.text
        note_uuid = note.json()["uuid"]
        body = _adopt(client, noteUuid=note_uuid, newTitle=None).json()
        content = client.get(f"/api/v1/library/notes/{note_uuid}").json()["contentMd"]
        assert content.startswith("原始内容")  # 追加不覆盖
        assert "来源：AI" in content

        deleted = client.delete(f"/api/v1/ai/answer-adoptions/{body['id']}")
        assert deleted.status_code == 204
        assert (
            client.get(f"/api/v1/library/notes/{note_uuid}").json()["contentMd"]
            == content  # 笔记内容不动
        )
        assert client.get("/api/v1/ai/answer-adoptions").json()["total"] == 0


def test_new279_validation():
    """空结论 422；不存在的落点笔记 422；未知采纳 404。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with _client(db) as client:
        assert (
            _adopt(client, conclusion="  ").status_code == 422
        )
        missing_note = _adopt(client, noteUuid="no-such-note", newTitle=None)
        assert missing_note.status_code == 422
        assert (
            client.patch(
                "/api/v1/ai/answer-adoptions/no-such",
                json={"conclusion": "x"},
            ).status_code
            == 404
        )


def test_new279_cross_user_adoptions_isolated(ab_env):  # noqa: F811
    """A 的采纳笔记对 B 不可见（笔记与台账都在 per-user 库）。"""
    env = ab_env
    client = env["client"]
    body = _adopt(client, headers=env["a"]).json()
    assert (
        client.get(
            f"/api/v1/library/notes/{body['noteUuid']}", headers=env["b"]
        ).status_code
        == 404
    )
    assert (
        client.get("/api/v1/ai/answer-adoptions", headers=env["b"]).json()["total"]
        == 0
    )
    assert (
        client.delete(
            f"/api/v1/ai/answer-adoptions/{body['id']}", headers=env["b"]
        ).status_code
        == 404
    )
