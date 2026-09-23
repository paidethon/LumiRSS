"""Cross-account RAG isolation regression (0067 security fix).

The bug: ``RagService`` holds ONE persistent sqlite-vec connection bound
to a concrete database file. A service cached on app.state (or a lazy
``db.path`` resolution) pinned WHICHEVER user's file resolved first —
every later account then read that user's vector index
(``users/<uid>/lumi.sqlite``) instead of their own.

The fix under test:
- ``_get_rag_service`` caches strictly per verified user id (the same
  ``(uid, "rag_service")`` slot the background loops use) and pins the
  vec-connection file at construction, inside the owning user's context;
- session mode never reads or mirrors the shared ``app.state.rag_service``
  handle, and an identity-less call fails closed;
- two users' indexes live in two different files and never cross, over
  the real HTTP surface (status/enable/rebuild/search).
"""

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import lumirss.rag as rag_module
from lumirss.deps import _get_rag_service
from lumirss.main import app
from lumirss.rag import MODEL_DIM, EmbeddingService
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database
from lumirss.user_scope import RoutingDatabase, user_context

DEPS_GET_RAG = _get_rag_service  # the deps seam under test
U1 = "u1isaaaa"
U2 = "u2isabbb"
REF1 = "library:u1-private-doc"
REF2 = "library:u2-private-doc"
TOKEN1 = "quantumcat"  # appears ONLY in u1's document
TOKEN2 = "seahorse"  # appears ONLY in u2's document

PASSWORD = "rag-" + __import__("secrets").token_urlsafe(9)


# ---- deps-level regression (per-user cache + pinned file) ------------------


def test_rag_service_cached_per_user_with_pinned_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    db = RoutingDatabase(tmp_path / "control.sqlite", tmp_path / "users")

    async def seed():
        with user_context(U1):
            await db.migrate()
            await LibrarySearchWriter(db).upsert(
                ref=REF1, kind="clip", title="u1 机密", body=f"只有 u1 可见：{TOKEN1} 协议笔记。", url=None
            )
        with user_context(U2):
            await db.migrate()
            await LibrarySearchWriter(db).upsert(
                ref=REF2, kind="clip", title="u2 笔记", body=f"u2 自己的普通 {TOKEN2} 笔记。", url=None
            )

    asyncio.run(seed())
    # A shared handle left on app.state must be IGNORED in session mode —
    # this is exactly the shape of the original leak.
    state = SimpleNamespace(db=db, user_services={}, rag_service="shared-sentinel")
    request = SimpleNamespace(app=SimpleNamespace(state=state))

    with user_context(U1):
        s1 = _get_rag_service(request)
        assert _get_rag_service(request) is s1  # cached per user
    with user_context(U2):
        s2 = _get_rag_service(request)
    assert s1 is not s2
    assert s1 is not state.rag_service  # never the shared handle
    assert state.rag_service == "shared-sentinel"  # and never mirrored into

    # Each vec connection is bound to its OWNER's file — PRAGMA
    # database_list reports the actual opened path.
    file1 = s1._vec_connection().execute("PRAGMA database_list").fetchone()[2]  # noqa: SLF001
    file2 = s2._vec_connection().execute("PRAGMA database_list").fetchone()[2]  # noqa: SLF001
    assert file1 == str(db.user_db_path(U1))
    assert file2 == str(db.user_db_path(U2))
    assert file1 != file2
    s1.close()
    s2.close()


def test_session_mode_without_identity_fails_closed(tmp_path, monkeypatch):
    from lumirss.user_scope import NoUserContextError

    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    state = SimpleNamespace(
        db=Database(tmp_path / "x.sqlite"), user_services={}, rag_service=None
    )
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    with pytest.raises(NoUserContextError):
        _get_rag_service(request)


# ---- HTTP-level regression (two members over the real surface) --------------


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
        for username in ("ragalice", "ragbob"):
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
            "owner": owner_headers,
            **cookies,
            "ids": ids,
            "users_root": tmp_path / "users",
        }


def _set_owner_password(db_path) -> None:
    from lumirss.accounts_store import AccountsStore, hash_password

    async def run():
        from lumirss.storage import Database

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
    """Deterministic embedder for every instance (no fastembed download)."""
    monkeypatch.setattr(rag_module, "_FASTEMBED_AVAILABLE", True)

    async def embed(self, texts):
        vectors = []
        for text in texts:
            vector = [0.0] * MODEL_DIM
            vector[len(text) % MODEL_DIM] = 1.0
            vectors.append(vector)
        return vectors

    monkeypatch.setattr(EmbeddingService, "embed", embed)


def _seed_user_doc(users_root, user_id: str, ref: str, title: str, body: str) -> None:
    db = RoutingDatabase(users_root.parent / "lumi.sqlite", users_root)

    async def seed():
        with user_context(user_id):
            await db.migrate()
            await LibrarySearchWriter(db).upsert(ref=ref, kind="clip", title=title, body=body, url=None)

    asyncio.run(seed())


def _chunks_file_ref(db_file, ref: str) -> int:
    connection = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT COUNT(*) AS n FROM rag_chunks WHERE ref = ?", (ref,)
        ).fetchone()
        return int(row[0])
    finally:
        connection.close()


def test_rag_search_and_index_never_cross_accounts(multi_env, fake_embedding):
    env = multi_env
    client = env["client"]
    alice_id, bob_id = env["ids"]["ragalice"], env["ids"]["ragbob"]
    _seed_user_doc(
        env["users_root"], alice_id, REF1,
        "alice 私有文档", f"alice 专属内容，{TOKEN1} 秘密配方，别人搜不到。",
    )
    _seed_user_doc(
        env["users_root"], bob_id, REF2,
        "bob 自己的文档", f"bob 记录的普通内容，{TOKEN2} 出没于此。",
    )

    # alice: enable + rebuild over HER index only.
    enabled = client.post("/api/v1/rag/enable", headers={"cookie": env["ragalice"]["cookie"]})
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["enabled"] is True
    rebuilt = client.post("/api/v1/rag/rebuild", headers={"cookie": env["ragalice"]["cookie"]})
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.json()["chunks"] >= 1

    # bob: rebuild too (never enabled → honest lexical-only mode).
    rebuilt_bob = client.post("/api/v1/rag/rebuild", headers={"cookie": env["ragbob"]["cookie"]})
    assert rebuilt_bob.status_code == 200, rebuilt_bob.text
    assert rebuilt_bob.json()["chunks"] >= 1

    def search(who: str, q: str):
        response = client.get(
            "/api/v1/rag/search", params={"q": q}, headers={"cookie": env[who]["cookie"]}
        )
        assert response.status_code == 200, response.text
        return response.json()

    # alice finds her own document (semantic leg live for her).
    alice_hits = search("ragalice", TOKEN1)
    assert [item["ref"] for item in alice_hits["items"]] == [REF1]
    assert alice_hits["semanticUsed"] is True
    # alice's index never surfaces BOB's document (the semantic KNN may
    # still return her own nearest chunk for an unrelated query — that
    # is her own data, not a leak).
    alice_miss = search("ragalice", TOKEN2)
    assert REF2 not in [item["ref"] for item in alice_miss["items"]]

    # bob finds his own document…
    bob_hits = search("ragbob", TOKEN2)
    assert [item["ref"] for item in bob_hits["items"]] == [REF2]
    # …but NOT alice's — the regression: a shared/pinned-wrong service
    # served alice's vector index (and lexical chunks) to bob.
    cross = search("ragbob", TOKEN1)
    assert REF1 not in [item["ref"] for item in cross["items"]]
    assert cross["semanticUsed"] is False  # bob never enabled RAG (per-user setting)
    # And a semantic-style probe from bob never surfaces alice's chunks.
    status_bob = client.get("/api/v1/rag/status", headers={"cookie": env["ragbob"]["cookie"]}).json()
    assert status_bob["enabled"] is False

    # The two indexes live in two DIFFERENT per-user database files.
    file_alice = env["users_root"] / alice_id / "lumi.sqlite"
    file_bob = env["users_root"] / bob_id / "lumi.sqlite"
    assert file_alice.is_file() and file_bob.is_file() and file_alice != file_bob
    assert _chunks_file_ref(file_alice, REF1) >= 1
    assert _chunks_file_ref(file_alice, REF2) == 0
    assert _chunks_file_ref(file_bob, REF2) >= 1
    assert _chunks_file_ref(file_bob, REF1) == 0
