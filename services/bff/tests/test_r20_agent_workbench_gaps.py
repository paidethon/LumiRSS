"""R20 Agent 工作台补缺 — 会话重命名 / 归档 / 停止生成（端点复验）/
会话导出到 Obsidian（R07 受限写入面复用）。

HTTP 契约级测试（client 夹具 = main app basic 模式，user 上下文由
中间件绑定）：
- 归档：PATCH archived → 默认列表收起、?archived=true 视图、恢复、
  搜索排除归档会话、未知会话 404；
- 重命名：PATCH title → 列表与设置同步；空白标题被裁剪；
- Obsidian 导出：未配置 → 逐项诚实 failed；配置 tmp vault → written
  + frontmatter source-type agent_thread；重复导出 → exists（content-id
  幂等）；空会话 422；未知会话 404。
"""

import asyncio

import pytest

from lumirss.agent_store import AgentStore
from lumirss.main import app


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def store(client):
    return AgentStore(app.state.db)


def _mk_thread(client, title="R20 会话"):
    resp = client.post("/api/v1/agent/threads")
    assert resp.status_code == 201
    thread = resp.json()
    if title:
        patch = client.patch(
            f"/api/v1/agent/threads/{thread['id']}", json={"title": title}
        )
        assert patch.status_code == 200
    return thread


# ---- R20 归档 / 重命名 -------------------------------------------------------


def test_r20_archive_hides_from_default_list_and_restores(client):
    keep = _mk_thread(client, "保留会话")
    gone = _mk_thread(client, "归档会话")

    resp = client.patch(
        f"/api/v1/agent/threads/{gone['id']}", json={"archived": True}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["archivedAt"] is not None

    default_ids = [
        t["id"] for t in client.get("/api/v1/agent/threads").json()["items"]
    ]
    assert keep["id"] in default_ids and gone["id"] not in default_ids

    archived = client.get("/api/v1/agent/threads", params={"archived": "true"})
    archived_ids = [t["id"] for t in archived.json()["items"]]
    assert gone["id"] in archived_ids and keep["id"] not in archived_ids
    hit = next(t for t in archived.json()["items"] if t["id"] == gone["id"])
    assert hit["archivedAt"] is not None

    # 恢复（archived=false）→ archived_at 清空，回到默认列表。
    restore = client.patch(
        f"/api/v1/agent/threads/{gone['id']}", json={"archived": False}
    )
    assert restore.status_code == 200
    assert restore.json()["archivedAt"] is None
    default_ids2 = [
        t["id"] for t in client.get("/api/v1/agent/threads").json()["items"]
    ]
    assert gone["id"] in default_ids2

    # 不传 archived 键 = 不改归档状态（归档过的重复 PATCH 其余设置）。
    client.patch(f"/api/v1/agent/threads/{gone['id']}", json={"archived": True})
    settings = client.patch(
        f"/api/v1/agent/threads/{gone['id']}", json={"clearScope": True}
    )
    assert settings.json()["archivedAt"] is not None


def test_r20_archived_thread_excluded_from_search(client, store):
    thread = _mk_thread(client, "归档搜索")
    run(
        store.append_message(
            thread["id"], role="user", content={"text": "唯一的归档大海针词"}
        )
    )
    resp = client.get("/api/v1/agent/threads/search", params={"q": "归档大海针词"})
    assert resp.status_code == 200
    assert any(item["threadId"] == thread["id"] for item in resp.json()["items"])

    client.patch(f"/api/v1/agent/threads/{thread['id']}", json={"archived": True})
    resp2 = client.get("/api/v1/agent/threads/search", params={"q": "归档大海针词"})
    assert all(
        item["threadId"] != thread["id"] for item in resp2.json()["items"]
    )


def test_r20_rename_updates_list_and_settings(client):
    thread = _mk_thread(client, "旧标题")
    resp = client.patch(
        f"/api/v1/agent/threads/{thread['id']}", json={"title": "  新标题  "}
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "新标题"
    listed = client.get("/api/v1/agent/threads").json()["items"]
    assert next(t for t in listed if t["id"] == thread["id"])["title"] == "新标题"
    missing = client.patch(
        "/api/v1/agent/threads/no-such-thread", json={"title": "x"}
    )
    assert missing.status_code == 404


def test_r20_thread_patch_clamps_title_and_rejects_bad_archived(client):
    """红线核对（R20 新端点面）：thread_id 等客户端输入不可信——超长
    标题服务端钳制到 100 字（agent_session.update_settings）；archived
    只接受布尔语义（Pydantic lax 归一 "yes"→True），数字 123 → 422，
    绝不静默解释为真值。"""
    thread = _mk_thread(client, "钳制")
    clamped = client.patch(
        f"/api/v1/agent/threads/{thread['id']}",
        json={"title": "长" * 250},
    )
    assert clamped.status_code == 200
    assert len(clamped.json()["title"]) == 100
    coerced = client.patch(
        f"/api/v1/agent/threads/{thread['id']}", json={"archived": "yes"}
    )
    assert coerced.status_code == 200
    assert coerced.json()["archivedAt"] is not None
    bad_type = client.patch(
        f"/api/v1/agent/threads/{thread['id']}", json={"archived": 123}
    )
    assert bad_type.status_code == 422


# ---- R20 会话导出到 Obsidian -------------------------------------------------


def _seed_thread_with_message(store, title="导出到库"):
    thread = run(store.create_thread(title))
    run(
        store.append_message(
            thread["id"],
            role="user",
            content={"text": "帮我总结最近的阅读"},
        )
    )
    run(
        store.append_message(
            thread["id"], role="assistant", content={"text": "最近你读了三类内容。"}
        )
    )
    return thread


def test_r20_obsidian_export_unconfigured_is_honest_failed(client, store, monkeypatch):
    monkeypatch.delenv("LUMIRSS_OBSIDIAN_EXPORT_DIR", raising=False)
    thread = _seed_thread_with_message(store)
    resp = client.post(
        f"/api/v1/agent/threads/{thread['id']}/obsidian-export", json={}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["reason"] == "export_unconfigured"
    assert body["path"] is None


def test_r20_obsidian_export_writes_markdown_and_is_idempotent(
    client, store, tmp_path, monkeypatch
):
    vault = tmp_path / "vault-export"
    vault.mkdir()
    monkeypatch.setenv("LUMIRSS_OBSIDIAN_EXPORT_DIR", str(vault))
    thread = _seed_thread_with_message(store)

    resp = client.post(
        f"/api/v1/agent/threads/{thread['id']}/obsidian-export",
        json={"rounds": 5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "written"
    assert body["ref"] == f"agent:{thread['id']}"
    written = vault / body["path"]
    assert written.is_file()
    text = written.read_text(encoding="utf-8")
    assert "source-type: \"agent_thread\"" in text
    assert f"lumirss-ref: \"agent:{thread['id']}\"" in text
    assert "帮我总结最近的阅读" in text

    # 重复导出 → exists（content-id 幂等，绝不覆盖既有文件）。
    resp2 = client.post(
        f"/api/v1/agent/threads/{thread['id']}/obsidian-export", json={}
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "exists"
    assert resp2.json()["contentId"] == body["contentId"]


def test_r20_obsidian_export_empty_thread_422_and_unknown_404(
    client, store, tmp_path, monkeypatch
):
    monkeypatch.setenv("LUMIRSS_OBSIDIAN_EXPORT_DIR", str(tmp_path / "vault"))
    (tmp_path / "vault").mkdir()
    empty = run(store.create_thread("空会话"))
    resp = client.post(
        f"/api/v1/agent/threads/{empty['id']}/obsidian-export", json={}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["type"] == "invalid_export_request"

    missing = client.post(
        "/api/v1/agent/threads/no-such-thread/obsidian-export", json={}
    )
    assert missing.status_code == 404


# ---- R20 停止生成（端点复验：无活动回合 → 稳定 409 信封） --------------------


def test_r20_cancel_without_active_run_is_stable_error(client, store):
    thread = _mk_thread(client, "停止复验")
    resp = client.post(f"/api/v1/agent/threads/{thread['id']}/cancel")
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["type"] == "no_active_run"
    missing = client.post("/api/v1/agent/threads/none/cancel")
    assert missing.status_code == 404
