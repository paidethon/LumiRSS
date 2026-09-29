"""NEW-239 标注冲突解决器 — 版本列冲突检测 / 并排 / 四种解决 / 隔离。

- baseVersion 命中 → 应用并 bump；过期 → 409 + 编辑暂存（绝不丢弃）；
- keep_server / keep_pending（服务端版入 conflict 快照）/ keep_both
  （副本新笔记）/ merged；全部写解决台账；
- 校验：非法 resolution 422；未知 pending 404；隔离：B 不可见 A 的
  冲突素材。
"""

from new231_helpers import ab_session


def _create_note(client, title: str = "两台设备的笔记", content: str = "初始版本\n") -> dict:
    response = client.post("/api/v1/library/notes", json={"title": title, "contentMd": content})
    assert response.status_code == 201, response.text
    return response.json()


def test_new239_conflict_detect_and_keep_server(client):
    """命中版本直接应用；过期版本 409 暂存；keep_server 丢弃暂存。"""
    note = _create_note(client)
    note_id = note["uuid"]

    # 设备 A：baseVersion=1 命中 → 应用，version=2
    applied = client.post(
        f"/api/v1/library/notes/{note_id}/conflicted-edits",
        json={"title": "两台设备的笔记", "contentMd": "设备 A 的修改\n", "baseVersion": 1, "deviceLabel": "device-a"},
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["outcome"] == "applied"
    assert body["note"]["version"] == 2

    # 设备 B：仍基于 version=1 → 409，编辑暂存，并排素材齐备
    conflict = client.post(
        f"/api/v1/library/notes/{note_id}/conflicted-edits",
        json={"title": "两台设备的笔记", "contentMd": "设备 B 的修改\n", "baseVersion": 1, "deviceLabel": "device-b"},
    )
    assert conflict.status_code == 409, conflict.text
    cbody = conflict.json()
    assert cbody["outcome"] == "conflict"
    pending_id = cbody["pendingEditId"]
    assert cbody["server"]["contentMd"] == "设备 A 的修改\n"
    assert cbody["server"]["version"] == 2
    assert cbody["incoming"]["contentMd"] == "设备 B 的修改\n"

    # 并排素材端点
    side = client.get(f"/api/v1/library/notes/{note_id}/conflicted-edits")
    assert side.status_code == 200
    side_body = side.json()
    assert side_body["server"]["version"] == 2
    assert [p["id"] for p in side_body["pending"]] == [pending_id]
    assert side_body["pending"][0]["deviceLabel"] == "device-b"

    # keep_server：丢弃 pending，正文不变
    resolved = client.post(
        f"/api/v1/library/notes/{note_id}/conflicted-edits/{pending_id}/resolve",
        json={"resolution": "keep_server"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["resolution"] == "keep_server"
    assert resolved.json()["note"]["contentMd"] == "设备 A 的修改\n"

    # 台账 + pending 清空
    log = client.get(f"/api/v1/library/notes/{note_id}/conflict-log").json()
    assert [entry["resolution"] for entry in log["items"]] == ["keep_server"]
    assert client.get(f"/api/v1/library/notes/{note_id}/conflicted-edits").json()["pending"] == []

    # 重复解决同一 pending → 404
    again = client.post(
        f"/api/v1/library/notes/{note_id}/conflicted-edits/{pending_id}/resolve",
        json={"resolution": "keep_server"},
    )
    assert again.status_code == 404


def test_new239_keep_pending_keep_both_and_merged(client):
    """keep_pending（覆盖前快照）/ keep_both（副本笔记）/ merged。"""
    note = _create_note(client, title="多解笔记", content="初始版本\n")
    note_id = note["uuid"]
    client.post(
        f"/api/v1/library/notes/{note_id}/conflicted-edits",
        json={"title": "多解笔记", "contentMd": "A 版\n", "baseVersion": 1},
    )

    # B 的过期编辑
    conflict = client.post(
        f"/api/v1/library/notes/{note_id}/conflicted-edits",
        json={"title": "多解笔记", "contentMd": "B 版\n", "baseVersion": 1},
    )
    pending_id = conflict.json()["pendingEditId"]

    # keep_pending：B 版覆盖；A 版先入 conflict 快照（历史不覆盖）
    kept = client.post(
        f"/api/v1/library/notes/{note_id}/conflicted-edits/{pending_id}/resolve",
        json={"resolution": "keep_pending"},
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["note"]["contentMd"] == "B 版\n"
    assert kept.json()["note"]["version"] == 3
    snapshot_id = kept.json()["conflictSnapshotVersionId"]
    assert snapshot_id

    async def _snapshot_origin():

        from lumirss.main import app
        from lumirss.user_scope import user_context
        with user_context(app.state.owner_id):
            row = await app.state.db.fetch_one(
                "SELECT origin, content_md FROM note_versions WHERE id = ?", (snapshot_id,)
            )
            return dict(row) if row else None

    import asyncio as _asyncio

    snapshot = _asyncio.run(_snapshot_origin())
    assert snapshot is not None
    assert snapshot["origin"] == "conflict"
    assert snapshot["content_md"] == "A 版\n"

    # keep_both：再制造一次冲突，副本另存为新笔记
    conflict2 = client.post(
        f"/api/v1/library/notes/{note_id}/conflicted-edits",
        json={"title": "多解笔记", "contentMd": "C 版（另存）\n", "baseVersion": 2},
    )
    assert conflict2.status_code == 409
    pending2 = conflict2.json()["pendingEditId"]
    both = client.post(
        f"/api/v1/library/notes/{note_id}/conflicted-edits/{pending2}/resolve",
        json={"resolution": "keep_both"},
    )
    assert both.status_code == 200, both.text
    copy_id = both.json()["copyNoteId"]
    assert copy_id and copy_id != note_id
    copy = client.get(f"/api/v1/library/notes/{copy_id}")
    assert copy.status_code == 200
    assert copy.json()["title"] == "多解笔记（冲突副本）"
    assert copy.json()["contentMd"] == "C 版（另存）\n"
    assert both.json()["note"]["contentMd"] == "B 版\n"  # 原笔记未动

    # merged：用户合并后的文本落库
    conflict3 = client.post(
        f"/api/v1/library/notes/{note_id}/conflicted-edits",
        json={"title": "多解笔记", "contentMd": "D 版\n", "baseVersion": 99},
    )
    assert conflict3.status_code == 409
    pending3 = conflict3.json()["pendingEditId"]
    merged = client.post(
        f"/api/v1/library/notes/{note_id}/conflicted-edits/{pending3}/resolve",
        json={"resolution": "merged", "title": "合并稿", "contentMd": "A/B/D 合并后的正文\n"},
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["note"]["contentMd"] == "A/B/D 合并后的正文\n"
    assert merged.json()["note"]["title"] == "合并稿"

    log = client.get(f"/api/v1/library/notes/{note_id}/conflict-log").json()["items"]
    assert [entry["resolution"] for entry in log] == ["merged", "keep_both", "keep_pending"]


def test_new239_validation_and_isolation(monkeypatch, tmp_path):
    """非法 resolution / 非法 baseVersion → 422；未知 pending → 404；
    B 访问 A 的冲突素材 → 404。"""
    with ab_session(monkeypatch, tmp_path) as session:
        note = session.client.post(
            "/api/v1/library/notes",
            json={"title": "A 的笔记", "contentMd": "初始\n"},
            headers=session.owner,
        ).json()
        note_id = note["uuid"]

        bad_version = session.client.post(
            f"/api/v1/library/notes/{note_id}/conflicted-edits",
            json={"title": "x", "contentMd": "y", "baseVersion": "one"},
            headers=session.owner,
        )
        assert bad_version.status_code == 422

        # 先推进一版（version=2），再让过期编辑（baseVersion=1）产生冲突
        applied = session.client.post(
            f"/api/v1/library/notes/{note_id}/conflicted-edits",
            json={"title": "A 的笔记", "contentMd": "第一版修改\n", "baseVersion": 1},
            headers=session.owner,
        )
        assert applied.status_code == 200

        conflict = session.client.post(
            f"/api/v1/library/notes/{note_id}/conflicted-edits",
            json={"title": "A 的笔记", "contentMd": "A 改\n", "baseVersion": 1},
            headers=session.owner,
        )
        assert conflict.status_code == 409
        pending_id = conflict.json()["pendingEditId"]

        bad_resolution = session.client.post(
            f"/api/v1/library/notes/{note_id}/conflicted-edits/{pending_id}/resolve",
            json={"resolution": "random"},
            headers=session.owner,
        )
        assert bad_resolution.status_code == 422

        member = session.activate_member("n239b")
        assert (
            session.client.get(
                f"/api/v1/library/notes/{note_id}/conflicted-edits", headers=member
            ).status_code
            == 404
        )
        assert (
            session.client.post(
                f"/api/v1/library/notes/{note_id}/conflicted-edits/{pending_id}/resolve",
                json={"resolution": "keep_server"},
                headers=member,
            ).status_code
            == 404
        )
