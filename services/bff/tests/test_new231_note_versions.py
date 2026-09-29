"""NEW-231 笔记修订对照 — 快照 / 差异 / 恢复（恢复记录）+ 跨用户隔离。

- 快照 → diff（逐行、增删计数、identical）→ 恢复（pre_restore 自动
  快照、恢复记录台账、搜索投影同步）；
- 校验：未知笔记/版本 404；恢复 current 422；
- 隔离：per-user 库——A 的笔记版本对 B 是 404。
"""

import asyncio

from lumirss.main import app
from lumirss.user_scope import user_context


def _run(coroutine):
    return asyncio.run(coroutine)


def _create_note(client, title: str, content: str) -> dict:
    response = client.post(
        "/api/v1/library/notes", json={"title": title, "contentMd": content}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_new231_snapshot_diff_restore_with_log(client):
    """快照 v1 → 修改正文 → diff 展示增删 → 恢复 v1 → 恢复记录在案，
    恢复前当前版自动进快照（历史不被覆盖）。"""
    created = _create_note(client, "读书笔记", "第一段原文\n第二段原文\n")
    note_id = created["uuid"]

    snap = client.post(f"/api/v1/library/notes/{note_id}/versions")
    assert snap.status_code == 201, snap.text
    version = snap.json()
    assert version["origin"] == "manual"
    assert version["noteId"] == note_id

    # 修改正文（走既有 PATCH 乐观锁路径）
    patch = client.patch(
        f"/api/v1/library/notes/{note_id}",
        json={
            "contentMd": "第一段原文\n改写后的第二段\n新增第三段\n",
            "baseUpdatedAt": created["updatedAt"],
        },
    )
    assert patch.status_code == 200, patch.text

    # diff：v1 vs current
    diff = client.get(
        f"/api/v1/library/notes/{note_id}/versions/diff",
        params={"fromVersion": version["id"]},
    )
    assert diff.status_code == 200, diff.text
    body = diff.json()
    assert body["fromVersion"] == version["id"]
    assert body["toVersion"] == "current"
    assert body["identical"] is False
    assert body["addedLines"] >= 1
    assert body["removedLines"] >= 1
    assert "改写后的第二段" in body["unified"]

    # diff 自身 → identical（诚实空 diff）
    same = client.get(
        f"/api/v1/library/notes/{note_id}/versions/diff",
        params={"fromVersion": version["id"], "toVersion": version["id"]},
    )
    assert same.status_code == 200
    assert same.json()["identical"] is True

    # 恢复 v1
    restore = client.post(
        f"/api/v1/library/notes/{note_id}/versions/{version['id']}/restore"
    )
    assert restore.status_code == 200, restore.text
    restored = restore.json()
    assert restored["restoredFrom"] == version["id"]
    assert restored["contentMd"] == "第一段原文\n第二段原文\n"
    assert restored["preRestoreVersionId"]

    # 当前内容回到 v1；恢复前的修改版以 pre_restore 快照保留（不覆盖历史）
    detail = client.get(f"/api/v1/library/notes/{note_id}")
    assert detail.status_code == 200
    assert "第二段原文" in detail.json()["contentMd"]
    assert "改写后的第二段" not in detail.json()["contentMd"]

    versions = client.get(f"/api/v1/library/notes/{note_id}/versions").json()
    origins = {item["id"]: item["origin"] for item in versions["items"]}
    assert origins[restored["preRestoreVersionId"]] == "pre_restore"
    assert versions["current"]["title"] == "读书笔记"

    # 恢复记录台账（只追加）
    log = client.get(f"/api/v1/library/notes/{note_id}/versions/restores")
    assert log.status_code == 200
    entries = log.json()["items"]
    assert len(entries) == 1
    assert entries[0]["versionId"] == version["id"]
    assert entries[0]["versionOrigin"] == "manual"

    # 搜索投影与恢复后的正文一致（旧投影里的「新增第三段」消失）
    async def _projection_body():
        with user_context(app.state.owner_id):
            row = await app.state.db.fetch_one(
                "SELECT body FROM search_library WHERE ref = ?", (f"note:{note_id}",)
            )
            return str(row["body"]) if row is not None else None

    body_text = _run(_projection_body())
    assert body_text is not None
    assert "第二段原文" in body_text
    assert "新增第三段" not in body_text


def test_new231_validation_and_missing(client):
    """未知笔记/版本 404；恢复 current 422。"""
    created = _create_note(client, "校验笔记", "唯一一段\n")
    note_id = created["uuid"]

    missing_note = client.post("/api/v1/library/notes/no-such/versions")
    assert missing_note.status_code == 404
    assert missing_note.json()["error"]["type"] == "note_version_not_found"

    missing_list = client.get("/api/v1/library/notes/no-such/versions")
    assert missing_list.status_code == 404

    missing_diff = client.get(
        f"/api/v1/library/notes/{note_id}/versions/diff",
        params={"fromVersion": "no-such-version"},
    )
    assert missing_diff.status_code == 404

    missing_log = client.get("/api/v1/library/notes/no-such/versions/restores")
    assert missing_log.status_code == 404

    current_restore = client.post(
        f"/api/v1/library/notes/{note_id}/versions/current/restore"
    )
    assert current_restore.status_code == 422
    assert current_restore.json()["error"]["type"] == "invalid_note_version"

    missing_restore = client.post(
        f"/api/v1/library/notes/{note_id}/versions/no-such-version/restore"
    )
    assert missing_restore.status_code == 404


def test_new231_cross_user_versions_isolated(monkeypatch, tmp_path):
    """A/B 隔离：A 快照的版本，B 的所有版本路由访问 → 404。"""
    from new231_helpers import ab_session

    with ab_session(monkeypatch, tmp_path) as session:
        # A（owner）建笔记 + 快照
        created = session.client.post(
            "/api/v1/library/notes",
            json={"title": "A 的笔记", "contentMd": "A 的内容\n"},
            headers=session.owner,
        )
        assert created.status_code == 201, created.text
        note_id = created.json()["uuid"]
        snap = session.client.post(
            f"/api/v1/library/notes/{note_id}/versions", headers=session.owner
        )
        assert snap.status_code == 201
        version_id = snap.json()["id"]

        member = session.activate_member("n231b")

        # B 以各路由访问 A 的笔记版本 → 一律 404（A 的私有版本对 B 不存在）
        for path in (
            f"/api/v1/library/notes/{note_id}/versions",
            f"/api/v1/library/notes/{note_id}/versions/diff?fromVersion={version_id}",
            f"/api/v1/library/notes/{note_id}/versions/restores",
        ):
            response = session.client.get(path, headers=member)
            assert response.status_code == 404, (path, response.status_code)
        for path in (
            f"/api/v1/library/notes/{note_id}/versions",
            f"/api/v1/library/notes/{note_id}/versions/{version_id}/restore",
        ):
            response = session.client.post(path, headers=member)
            assert response.status_code == 404, (path, response.status_code)
