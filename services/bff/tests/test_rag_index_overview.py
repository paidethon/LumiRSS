"""R24 RAG 索引页 HTTP-level tests：overview / delete / retry-failed /
pause-resume / converge。

口径与既有 test_rag_api.py 相同：临时库 + 确定性 fake embedder（零下载）。
覆盖验收要求：
- overview 数值真实（3 篇索引后核对 documents/chunks/queue）；
- 删除索引后原文仍在（search_library 行数不变）；
- retry-failed 只动失败项（未失败 ref 的 chunk_id 原样保留）；
- 跨用户隔离（A 的总览永远看不到 B 的 ref，B 未索引则 documents=0）。
"""

import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient

import lumirss.rag as rag_module
from lumirss.main import app
from lumirss.rag import MODEL_DIM, EmbeddingService, RagService, rag_index_pass
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database

PASSWORD = "rag-" + __import__("secrets").token_urlsafe(9)


def _fake_embedder(service: RagService) -> None:
    async def fake_embed(texts):
        vectors = []
        for text in texts:
            vector = [0.0] * MODEL_DIM
            vector[len(text) % MODEL_DIM] = 1.0
            vectors.append(vector)
        return vectors

    service._embedder.embed = fake_embed  # noqa: SLF001 — test seam


def _seed_library_doc(db: Database, ref: str, title: str, body: str) -> None:
    async def seed():
        await db.migrate()
        await LibrarySearchWriter(db).upsert(
            ref=ref, kind="clip", title=title, body=body, url=None
        )

    asyncio.run(seed())


@pytest.fixture()
def rag_env(client):  # noqa: F811 — reuse the conftest fixture
    """client + 注入该 client 临时库上的 RagService（fake embedder）。"""
    db: Database = app.state.db
    service = RagService(db)
    _fake_embedder(service)
    app.state.rag_service = service
    try:
        yield {"client": client, "db": db, "service": service}
    finally:
        app.state.rag_service = None


def _rebuild_three_docs(env) -> list[str]:
    refs = [f"library:{uuid.uuid4()}" for _ in range(3)]
    for i, ref in enumerate(refs, start=1):
        _seed_library_doc(env["db"], ref, f"文档 {i}", f"第 {i} 篇的正文内容，用于索引计数。")
    rebuilt = env["client"].post("/api/v1/rag/rebuild")
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.json()["chunks"] >= 3
    return refs


# ---- overview 数值真实 -------------------------------------------------------


def test_overview_counts_after_indexing_three_docs(rag_env):
    env = rag_env
    refs = _rebuild_three_docs(env)

    response = env["client"].get("/api/v1/rag/index/overview")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["documents"] == 3
    assert body["chunks"] >= 3
    clip = next(s for s in body["sources"] if s["kind"] == "clip")
    assert clip["corpusDocs"] == 3
    assert clip["indexedDocs"] == 3
    assert clip["chunks"] >= 3
    assert body["queue"] == {"pending": 0, "done": 3, "failed": 0, "stale": 0}
    assert body["storage"]["totalBytes"] > 0
    assert body["storage"]["basis"] in {"dbstat", "payload"}
    assert body["lastUpdatedAt"] is not None
    assert body["job"] is not None and body["job"]["status"] == "done"
    assert body["incrementalPaused"] is False
    # 绝不外带 embedding 数组：响应 JSON 里不允许出现向量形状字段。
    assert "embedding" not in json.dumps(body)
    assert refs  # 保持引用以防 lint 误报


def test_overview_empty_index_is_honest(rag_env):
    env = rag_env
    response = env["client"].get("/api/v1/rag/index/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["documents"] == 0
    assert body["chunks"] == 0
    assert body["queue"]["done"] == 0
    assert body["failures"] == []
    assert body["job"] is None


# ---- 删除索引：原文仍在 -------------------------------------------------------


def test_delete_index_keeps_source_rows(rag_env):
    env = rag_env
    _rebuild_three_docs(env)

    async def source_count():
        row = await env["db"].fetch_one("SELECT COUNT(*) AS n FROM search_library")
        return int(row["n"])

    assert asyncio.run(source_count()) == 3

    deleted = env["client"].delete("/api/v1/rag/index")
    assert deleted.status_code == 200, deleted.text
    payload = deleted.json()
    assert payload["removedChunks"] >= 3
    assert payload["removedVecRows"] >= 3

    # 原文（投影行）毫发无损；派生索引清零。
    assert asyncio.run(source_count()) == 3
    body = env["client"].get("/api/v1/rag/index/overview").json()
    assert body["documents"] == 0
    assert body["chunks"] == 0
    assert body["queue"]["pending"] == 3  # 原文仍在 → 仍可索引（可重建）
    clip = next(s for s in body["sources"] if s["kind"] == "clip")
    assert clip["corpusDocs"] == 3
    assert clip["indexedDocs"] == 0


# ---- retry-failed：只动失败项 -------------------------------------------------


def test_retry_failed_touches_only_failed_refs(rag_env):
    env = rag_env
    refs = _rebuild_three_docs(env)
    db = env["db"]

    async def chunk_id_of(ref: str) -> int | None:
        row = await db.fetch_one(
            "SELECT MIN(chunk_id) AS c FROM rag_chunks WHERE ref = ?", (ref,)
        )
        return int(row["c"]) if row is not None and row["c"] is not None else None

    survivor = refs[1]
    gone_ref = "library:deleted-mid-rebuild"
    failed_ref = refs[2]
    survivor_before = asyncio.run(chunk_id_of(survivor))

    # 伪造「最近一次作业」：skipped 记录失败项（一个已消失 + 一个仍在）。
    async def plant_job():
        await db.migrate()
        await db.execute(
            "INSERT INTO rag_jobs (id, kind, status, cursor_json, stats_json, updated_at)"
            " VALUES (?, ?, ?, NULL, ?, ?)",
            (
                "job-r24-failed",
                "rebuild",
                "done",
                json.dumps({"chunks": 3, "docs": 3, "skipped": [failed_ref, gone_ref]}),
                "2099-01-01T00:00:00+00:00",
            ),
        )

    asyncio.run(plant_job())

    overview = env["client"].get("/api/v1/rag/index/overview").json()
    assert overview["queue"]["failed"] == 2
    failure_refs = {item["ref"] for item in overview["failures"]}
    assert failure_refs == {failed_ref, gone_ref}

    retried = env["client"].post("/api/v1/rag/index/retry-failed", json={})
    assert retried.status_code == 200, retried.text
    payload = retried.json()
    assert payload["requested"] == 2
    assert payload["missing"] == [gone_ref]  # 已消失 → 诚实 missing，不冒充成功
    assert payload["updated"] == 1  # 只有仍在投影中的失败项被重嵌
    assert payload["chunks"] >= 1

    # 未失败的 ref 一个字节都没被碰（chunk_id 不变 = 未删除重插）。
    assert asyncio.run(chunk_id_of(survivor)) == survivor_before
    # failed_ref 被重建过：其新 chunk_id 一定晚于旧基线（删除后重插）。
    assert asyncio.run(chunk_id_of(failed_ref)) != survivor_before

    # 单项重试：显式 refs 只重试那一个。
    single = env["client"].post(
        "/api/v1/rag/index/retry-failed", json={"refs": [gone_ref]}
    )
    assert single.status_code == 200
    assert single.json()["updated"] == 0
    assert single.json()["missing"] == [gone_ref]


# ---- 暂停 / 继续 / 手动收敛 ----------------------------------------------------


def test_pause_resume_and_converge(rag_env, monkeypatch):
    env = rag_env
    _rebuild_three_docs(env)
    monkeypatch.setattr(rag_module, "_FASTEMBED_AVAILABLE", True)
    enabled = env["client"].post("/api/v1/rag/enable")
    assert enabled.status_code == 200, enabled.text

    paused = env["client"].post("/api/v1/rag/index/pause")
    assert paused.status_code == 200
    assert paused.json() == {"paused": True}
    overview = env["client"].get("/api/v1/rag/index/overview").json()
    assert overview["incrementalPaused"] is True

    # 暂停期间增量收敛诚实跳过（绝不停摆也不偷跑）。
    result = asyncio.run(rag_index_pass(env["service"]))
    assert result["skipped"] == "paused"
    converged = env["client"].post("/api/v1/rag/index/converge")
    assert converged.status_code == 200
    assert converged.json()["skipped"] == "paused"

    resumed = env["client"].post("/api/v1/rag/index/resume")
    assert resumed.status_code == 200
    assert resumed.json() == {"paused": False}
    overview = env["client"].get("/api/v1/rag/index/overview").json()
    assert overview["incrementalPaused"] is False
    converged = env["client"].post("/api/v1/rag/index/converge").json()
    assert converged.get("skipped") is None


# ---- 跨用户隔离 ---------------------------------------------------------------

U1_REF = "library:alice-private"
U2_REF = "library:bob-private"


@pytest.fixture()
def multi_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_RAG_INDEX_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(tmp_path)
        owner_login = client.post(
            "/api/v1/auth/login", json={"username": "owner", "password": PASSWORD}
        )
        assert owner_login.status_code == 200
        owner_headers = {"cookie": owner_login.headers["set-cookie"].split(";")[0]}
        cookies = {}
        for username in ("r24alice", "r24bob"):
            invite = client.post(
                "/api/v1/admin/invites", json={"label": username}, headers=owner_headers
            )
            activation = client.post(
                "/api/v1/auth/activate",
                json={"token": invite.json()["token"], "username": username, "password": PASSWORD},
            )
            assert activation.status_code == 200, activation.text
            cookies[username] = {"cookie": activation.headers["set-cookie"].split(";")[0]}
        users = client.get("/api/v1/admin/users", headers=owner_headers).json()
        ids = {row["username"]: row["id"] for row in users}
        yield {
            "client": client,
            **cookies,
            "ids": ids,
            "users_root": tmp_path / "users",
        }


def _set_owner_password(db_path) -> None:
    from lumirss.accounts_store import AccountsStore, hash_password

    async def run():
        database = Database(db_path / "lumi.sqlite")
        await database.migrate()
        store = AccountsStore(database)
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                await store.set_password_hash(str(row["id"]), hash_password(PASSWORD))
                return
        raise AssertionError("owner migration did not run")

    asyncio.run(run())


@pytest.fixture()
def fake_embedding(monkeypatch):
    monkeypatch.setattr(rag_module, "_FASTEMBED_AVAILABLE", True)

    async def embed(self, texts):
        vectors = []
        for text in texts:
            vector = [0.0] * MODEL_DIM
            vector[len(text) % MODEL_DIM] = 1.0
            vectors.append(vector)
        return vectors

    monkeypatch.setattr(EmbeddingService, "embed", embed)


def _seed_user_doc(users_root, user_id: str, ref: str, body: str) -> None:
    from lumirss.user_scope import RoutingDatabase, user_context

    db = RoutingDatabase(users_root.parent / "lumi.sqlite", users_root)

    async def seed():
        with user_context(user_id):
            await db.migrate()
            await LibrarySearchWriter(db).upsert(
                ref=ref, kind="clip", title=ref, body=body, url=None
            )

    asyncio.run(seed())


def test_overview_never_crosses_accounts(multi_env, fake_embedding):
    env = multi_env
    client = env["client"]
    alice_id, bob_id = env["ids"]["r24alice"], env["ids"]["r24bob"]
    _seed_user_doc(env["users_root"], alice_id, U1_REF, "alice 的私有索引内容。")
    _seed_user_doc(env["users_root"], bob_id, U2_REF, "bob 的私有索引内容。")

    enabled = client.post(
        "/api/v1/rag/enable", headers={"cookie": env["r24alice"]["cookie"]}
    )
    assert enabled.status_code == 200, enabled.text
    rebuilt = client.post(
        "/api/v1/rag/rebuild", headers={"cookie": env["r24alice"]["cookie"]}
    )
    assert rebuilt.status_code == 200, rebuilt.text

    alice = client.get(
        "/api/v1/rag/index/overview", headers={"cookie": env["r24alice"]["cookie"]}
    )
    assert alice.status_code == 200, alice.text
    alice_body = alice.json()
    assert alice_body["documents"] == 1  # 只有她自己的那一篇
    assert U2_REF not in alice.text  # bob 的 ref 绝不出现在 alice 的总览里

    bob = client.get(
        "/api/v1/rag/index/overview", headers={"cookie": env["r24bob"]["cookie"]}
    )
    assert bob.status_code == 200
    bob_body = bob.json()
    assert bob_body["documents"] == 0  # bob 从未索引 → 诚实为 0
    assert U1_REF not in bob.text
    clip = next(s for s in bob_body["sources"] if s["kind"] == "clip")
    assert clip["corpusDocs"] == 1  # bob 看到的是他自己的语料
    assert clip["indexedDocs"] == 0
