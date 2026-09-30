"""FIX-063 守卫：图片/正文/附件字节出口的跨用户归属基线。

背景（0067 架构）：所有字节出口（快照 page.html、笔记附件 content、
邮件附件、email-attachment-items）都经 request.app.state.db =
RoutingDatabase（按会话身份路由 per-user 库）解析记录后再读盘；
外来 ID 在 per-user 库中不存在 → 同型 404。既有跨用户证据：
test_n125（邮件附件下载）、test_new296（email-attachment-items 下载）、
test_new240（附件添加/清单）。本文件补上尚未钉住的两个出口：

1. 笔记附件 CONTENT 下载（GET /api/v1/library/notes/{id}/attachments/{aid}/content）；
2. 快照正文读出（GET /api/v1/library/assets/{uuid}/page.html，含 text-layer）。

A 账户写入 → B 账户与 owner 读取 → 同型 404（无存在性泄露）；
A 自读 200。这是基线钉子（BASELINE_OK 的硬证据），不是行为变更。
"""

import asyncio
import base64
import secrets

import pytest

from new231_helpers import ab_session


def _session_user_id(client, headers: dict[str, str]) -> str:
    probe = client.get("/api/v1/auth/session", headers=headers)
    assert probe.status_code == 200, probe.text
    return str(probe.json()["userId"])


def test_fix063_note_attachment_content_cross_user_404(monkeypatch, tmp_path):
    """A 的笔记附件：B / owner 拿不到内容（同型 404），A 自读 200。"""
    with ab_session(monkeypatch, tmp_path) as session:
        client = session.client
        alice = session.activate_member("fx063a")
        bob = session.activate_member("fx063b")

        note = client.post(
            "/api/v1/library/notes",
            json={"title": "A 的附件笔记", "contentMd": "正文\n"},
            headers=alice,
        )
        assert note.status_code == 201, note.text
        note_id = note.json()["uuid"]

        secret_bytes = b"fx063-" + secrets.token_bytes(16)
        added = client.post(
            f"/api/v1/library/notes/{note_id}/attachments",
            json={
                "filename": "private.txt",
                "mimeType": "text/plain",
                "contentBase64": base64.b64encode(secret_bytes).decode("ascii"),
            },
            headers=alice,
        )
        assert added.status_code == 201, added.text
        attachment_id = added.json()["id"]

        own = client.get(
            f"/api/v1/library/notes/{note_id}/attachments/{attachment_id}/content",
            headers=alice,
        )
        assert own.status_code == 200
        assert own.content == secret_bytes

        for outsider in (bob, session.owner):
            borrowed = client.get(
                f"/api/v1/library/notes/{note_id}/attachments/{attachment_id}/content",
                headers=outsider,
            )
            assert borrowed.status_code == 404


def test_fix063_snapshot_page_html_cross_user_404(monkeypatch, tmp_path):
    """A 的快照 page.html / text-layer：B 与 owner 同型 404，A 自读 200。

    资产按路由器同一约定落在 A 的 per-user 资产根
    users/<uid>/library/assets，行写进 A 的 per-user 库（user_context），
    B 的请求在其自己的库与根里解析 → 404。
    """
    with ab_session(monkeypatch, tmp_path) as session:
        client = session.client
        app = client.app
        alice = session.activate_member("fx063sa")
        bob = session.activate_member("fx063sb")
        alice_uid = _session_user_id(client, alice)

        from lumirss.library_assets import AssetStore
        from lumirss.user_scope import user_context

        root = app.state.users_root / alice_uid / "library" / "assets"
        snapshot_bytes = b"<html><body>fx063 snapshot</body></html>"

        def _save() -> str:
            async def _inner() -> str:
                store = AssetStore(app.state.db, root)
                record, _deduped = await store.save_snapshot(
                    data=snapshot_bytes, url="https://page.example/fx063"
                )
                return record.uuid

            with user_context(alice_uid):
                return asyncio.run(_inner())

        asset_uuid = _save()

        own = client.get(
            f"/api/v1/library/assets/{asset_uuid}/page.html", headers=alice
        )
        assert own.status_code == 200
        assert own.content == snapshot_bytes

        for outsider in (bob, session.owner):
            page = client.get(
                f"/api/v1/library/assets/{asset_uuid}/page.html",
                headers=outsider,
            )
            assert page.status_code == 404
            layer = client.get(
                f"/api/v1/library/snapshots/{asset_uuid}/text-layer",
                params={"q": "snapshot"},
                headers=outsider,
            )
            assert layer.status_code == 404

        detail = client.get(
            f"/api/v1/library/snapshots/{asset_uuid}", headers=session.owner
        )
        assert detail.status_code == 404


_ = pytest  # imported for parity with sibling suites; no direct use
