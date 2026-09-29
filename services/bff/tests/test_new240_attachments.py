"""NEW-240 笔记附件清单 — 添加 / 清单与容量 / 下载 / 移除留文字 / 隔离。

- 附件添加、容量视图、内容下载一致；移除只删附件，笔记正文不动；
- 限额：单文件 ≤256KB、每笔记 ≤10 个、同名拒绝；未知笔记/附件 404；
- 隔离：B 不能给 A 的笔记加附件（404）。
"""

import base64

from new231_helpers import ab_session


def _create_note(client) -> dict:
    response = client.post(
        "/api/v1/library/notes",
        json={"title": "带附件的笔记", "contentMd": "正文文字不动。\n"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add(client, note_id: str, filename: str, data: bytes, mime: str = "text/plain"):
    return client.post(
        f"/api/v1/library/notes/{note_id}/attachments",
        json={
            "filename": filename,
            "mimeType": mime,
            "contentBase64": base64.b64encode(data).decode("ascii"),
        },
    )


def test_new240_attachment_lifecycle_and_caps(client):
    """添加 → 清单（容量）→ 下载一致 → 同名拒绝 → 移除留文字 → 上限。"""
    note = _create_note(client)
    note_id = note["uuid"]

    added = _add(client, note_id, "摘录卡片.txt", "小卡片内容".encode(), "text/plain")
    assert added.status_code == 201, added.text
    item = added.json()
    assert item["filename"] == "摘录卡片.txt"
    assert item["sizeBytes"] == len("小卡片内容".encode())

    listing = client.get(f"/api/v1/library/notes/{note_id}/attachments")
    assert listing.status_code == 200
    body = listing.json()
    assert [row["id"] for row in body["items"]] == [item["id"]]
    assert body["usage"]["count"] == 1
    assert body["usage"]["totalBytes"] == item["sizeBytes"]
    assert body["usage"]["noteCapBytes"] == 1024 * 1024

    # 下载内容一致
    download = client.get(
        f"/api/v1/library/notes/{note_id}/attachments/{item['id']}/content"
    )
    assert download.status_code == 200
    assert download.content == "小卡片内容".encode()

    # 同名拒绝
    dup = _add(client, note_id, "摘录卡片.txt", b"other")
    assert dup.status_code == 422

    # 单文件超限（>256KB）
    big = _add(client, note_id, "大文件.bin", b"x" * (256 * 1024 + 1), "application/octet-stream")
    assert big.status_code == 422

    # 移除附件：笔记正文不动
    removed = client.delete(f"/api/v1/library/notes/{note_id}/attachments/{item['id']}")
    assert removed.status_code == 204
    detail = client.get(f"/api/v1/library/notes/{note_id}")
    assert detail.status_code == 200
    assert detail.json()["contentMd"] == "正文文字不动。\n"
    after = client.get(f"/api/v1/library/notes/{note_id}/attachments").json()
    assert after["items"] == []
    assert after["usage"]["count"] == 0

    # 数量上限：10 个之后拒绝
    ids = []
    for index in range(10):
        ok = _add(client, note_id, f"附件{index}.txt", f"内容{index}".encode())
        assert ok.status_code == 201, ok.text
        ids.append(ok.json()["id"])
    over = _add(client, note_id, "第11个.txt", "溢出".encode())
    assert over.status_code == 422

    # 未知笔记 / 未知附件
    assert (
        client.post(
            "/api/v1/library/notes/no-such/attachments",
            json={"filename": "x.txt", "contentBase64": base64.b64encode(b"x").decode()},
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/library/notes/{note_id}/attachments/no-such/content").status_code
        == 404
    )
    assert client.delete(f"/api/v1/library/notes/{note_id}/attachments/no-such").status_code == 404

    # 非法 base64 → 422
    bad = client.post(
        f"/api/v1/library/notes/{note_id}/attachments",
        json={"filename": "bad.txt", "contentBase64": "!!!not-base64!!!"},
    )
    assert bad.status_code == 422

    # 清理后可继续添加（容量恢复诚实）
    for attachment_id in ids:
        assert (
            client.delete(f"/api/v1/library/notes/{note_id}/attachments/{attachment_id}").status_code
            == 204
        )
    refill = _add(client, note_id, "再来一个.txt", b"ok")
    assert refill.status_code == 201


def test_new240_cross_user_attachments_isolated(monkeypatch, tmp_path):
    """B 不能给 A 的笔记加附件，也看不到其附件清单（404）。"""
    with ab_session(monkeypatch, tmp_path) as session:
        note = session.client.post(
            "/api/v1/library/notes",
            json={"title": "A 的笔记", "contentMd": "A 的正文\n"},
            headers=session.owner,
        ).json()
        member = session.activate_member("n240b")

        response = session.client.post(
            f"/api/v1/library/notes/{note['uuid']}/attachments",
            json={
                "filename": "b.txt",
                "contentBase64": base64.b64encode("B 的附件".encode()).decode(),
            },
            headers=member,
        )
        assert response.status_code == 404
        assert (
            session.client.get(
                f"/api/v1/library/notes/{note['uuid']}/attachments", headers=member
            ).status_code
            == 404
        )
        # A 自己可见且清单为空
        own = session.client.get(
            f"/api/v1/library/notes/{note['uuid']}/attachments", headers=session.owner
        )
        assert own.status_code == 200
        assert own.json()["items"] == []
