"""F090 Lumi 笔记全生命周期 — CRUD+乐观锁 409、软删→搜索不可见→恢复、
XSS 净化（md 渲染管线输入侧）、100KB 限制 422、重启持久、Vault 零写入负向。"""

import asyncio
import hashlib

from lumirss.main import app


def run(coro):
    return asyncio.run(coro)


def _search_visible(ref: str) -> dict | None:
    async def _q():
        await app.state.db.migrate()
        return await app.state.db.fetch_one(
            "SELECT ref FROM search_library WHERE ref = ?", (ref,)
        )

    return run(_q())


def test_f090_crud_conflict_and_limit(client):
    created = client.post(
        "/api/v1/library/notes",
        json={"title": " meeting 记录", "contentMd": "# 笔记\n内容A"},
    )
    assert created.status_code == 201, created.text
    note = created.json()
    assert note["title"] == "meeting 记录"
    # 搜索投影已写入
    assert _search_visible(f"note:{note['uuid']}") is not None
    # 更新（带乐观锁）
    updated = client.patch(
        f"/api/v1/library/notes/{note['uuid']}",
        json={"contentMd": "内容B", "baseUpdatedAt": note["updatedAt"]},
    )
    assert updated.status_code == 200, updated.text
    # stale 乐观锁 → 409 note_conflict（base 与当前 updatedAt 不一致）
    conflict = client.patch(
        f"/api/v1/library/notes/{note['uuid']}",
        json={"contentMd": "内容C", "baseUpdatedAt": "2000-01-01T00:00:00+00:00"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["type"] == "note_conflict"
    # 100KB 限制 → 422
    too_big = client.post(
        "/api/v1/library/notes",
        json={"title": "大笔记", "contentMd": "x" * (100 * 1024 + 1)},
    )
    assert too_big.status_code == 422
    # GET 详情
    got = client.get(f"/api/v1/library/notes/{note['uuid']}")
    assert got.status_code == 200 and got.json()["contentMd"] == "内容B"
    # 列表含摘要
    listed = client.get("/api/v1/library/notes").json()["items"]
    assert any(i["uuid"] == note["uuid"] for i in listed)


def test_f090_soft_delete_search_invisible_restore(client):
    note = client.post(
        "/api/v1/library/notes", json={"title": "待删笔记", "contentMd": "独关键词qwerty"}
    ).json()
    ref = f"note:{note['uuid']}"
    assert _search_visible(ref) is not None
    assert client.delete(f"/api/v1/library/notes/{note['uuid']}").status_code == 204
    # 软删 → 列表不可见 + 搜索投影移除
    listed = client.get("/api/v1/library/notes").json()["items"]
    assert all(i["uuid"] != note["uuid"] for i in listed)
    assert _search_visible(ref) is None
    # 回收站 kind=note 可见 → 恢复 → 搜索重新可见
    trash = client.get("/api/v1/library/trash", params={"type": "note"}).json()["items"]
    assert any(t["uuid"] == note["uuid"] and t["kind"] == "note" for t in trash)
    assert (
        client.post(f"/api/v1/library/trash/{note['uuid']}/restore").status_code
        == 204
    )
    assert _search_visible(ref) is not None
    assert any(i["uuid"] == note["uuid"] for i in client.get("/api/v1/library/notes").json()["items"])


def test_f090_md_render_never_executes_script(client, monkeypatch):
    """负向：`<script>` 内容进入 md 渲染管线时被净化（渲染输入侧守卫）。"""
    from lumirss.article_sanitize import sanitize_html

    dirty = "# t\n<script>alert(1)</script>\n<img src=x onerror=alert(2)>"
    html = sanitize_html(dirty)
    assert "<script" not in html.lower()
    assert "onerror" not in html.lower()


def test_f090_restart_persistence_and_vault_untouched(client, tmp_path):
    # Vault 零写入（负向）：记录目录哈希
    vault = tmp_path / "vault"
    vault.mkdir()

    def dir_hash():
        h = hashlib.sha256()
        for p in sorted(vault.rglob("*")):
            h.update(str(p.relative_to(vault)).encode())
            if p.is_file():
                h.update(p.read_bytes())
        return h.hexdigest()

    note = client.post(
        "/api/v1/library/notes",
        json={"title": "vault 负向", "contentMd": "内容持久化"},
        headers={"X-Vault-Dir": str(vault)},
    ).json()
    before = dir_hash()
    # 重启持久：新 TestClient 实例（同一 DB 文件）仍可读
    from fastapi.testclient import TestClient

    assert app.state.db.path  # 重启后同库文件（持久性前提）
    # 0067：重启（新 TestClient）的 lifespan 会把 app.state.db 重绑成
    # RoutingDatabase——先捕获普通 Database 句柄，启动后再覆盖回去
    #（与 conftest client fixture 同一约定）。
    plain_db = app.state.db
    with TestClient(app) as client2:
        client2.app.state.db = plain_db
        got = client2.get(f"/api/v1/library/notes/{note['uuid']}")
        assert got.status_code == 200
        assert got.json()["contentMd"] == "内容持久化"
    assert dir_hash() == before
