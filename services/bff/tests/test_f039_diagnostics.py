"""F039 脱敏诊断包 —— 结构完整、秘密不泄露、无认证语义随 operations。

带秘密的 fixture 环境下 grep 断言：响应不含密码/API key 值/条目正文。
"""

import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from lumirss.main import app

SECRET_LIKE = "super-secret-f039-value-不泄露"


def _wire(tmp: Path, monkeypatch):
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp / "lumi.sqlite"))
    monkeypatch.setenv("FRESHRSS_BASE_URL", "https://freshrss.example")
    monkeypatch.setenv("FRESHRSS_USERNAME", "user")
    monkeypatch.setenv("FRESHRSS_API_PASSWORD", SECRET_LIKE)
    monkeypatch.setenv("AI_API_KEY", SECRET_LIKE)


def test_f039_diagnostics_structure_and_no_secret_leak(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    with TestClient(app) as client:
        from lumirss.storage import Database

        # 0067：lifespan 绑定 RoutingDatabase（需要请求身份）；直连
        # 建库/断言按 conftest 同款约定覆盖为普通 Database（控制库文件）。
        client.app.state.db = Database(tmp_path / "lumi.sqlite")
        run = asyncio.run
        run(client.app.state.db.migrate())
        # freshrss presence 按用户绑定判定（basic 模式 = owner）：
        # 给 owner 种一行绑定（0068 后 freshrss_binding 在用户库）。
        owner_id = None
        for row in run(client.app.state.accounts.list_users(limit=10)):
            if row.get("role") == "owner":
                owner_id = str(row["id"])
        assert owner_id, "owner migration did not run"
        run(
            client.app.state.db.execute(
                "INSERT OR REPLACE INTO freshrss_binding (id, base_url, username, public_url, bound_at, source) VALUES (1, 'http://freshrss', 'user', '', 0, 'env')"
            )
        )
        # 带秘密形态的数据在库中（正文含秘密串）
        run(
            client.app.state.db.execute(
                "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, fetched_at) VALUES ('s1','e1.c2Ek','https://f.example/rss','源','t','a','u', ?, '2026-09-18T00:00:00Z', 0)",
                (f"正文包含 {SECRET_LIKE}",),
            )
        )
        resp = client.get("/api/v1/operations/diagnostics")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 结构完整
    for key in (
        "version",
        "schemaVersion",
        "authMode",
        "uptimeS",
        "deps",
        "errorCountsByType",
        "configPresence",
        "counts",
    ):
        assert key in body
    assert isinstance(body["deps"], list) and body["deps"]
    presence = body["configPresence"]
    assert presence["freshrss"] is True
    assert presence["aiKey"] is True
    assert presence["rsshub"] in (True, False)
    assert presence["obsidian"] in (True, False)
    assert body["counts"]["entriesIndexed"] >= 1

    # 秘密不泄露：响应全文 grep 不到秘密串/任何条目正文
    text = json.dumps(body)
    assert SECRET_LIKE not in text
    assert "正文包含" not in text
    assert "https://freshrss.example" not in text  # 查询串/URL 值不外带
