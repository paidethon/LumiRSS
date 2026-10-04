"""Native iOS client compatibility (SwiftUI v0.1.0) — server-side gate.

The iOS app consumes the SAME /api/v1 contract as the web client over a
URLSession cookie session (no Origin header, no CORS, no bearer token).
These tests pin the exact behaviors the native reader depends on, so a
server change that would break the app fails here first:

- cookie-session login/session-probe/logout round trip with the plain
  (non-browser) client profile: NO Origin header on unsafe methods;
- /api/v1/version as the unauthenticated compatibility probe;
- entries list → entry detail → PATCH state with SET semantics (a
  repeated read=true never flips back) and list readback consistency;
- a second account's session stays isolated (its identity resolves to
  its own user; its state writes route to its own scope);
- logout revokes server-side (the cookie stops working).

No real FreshRSS: the adapter is stubbed per the suite convention.
"""

import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.adapters.freshrss import EntryPage
from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.models import EntryDetail, EntryListItem
from lumirss.storage import Database

PASSWORD = "pw-" + _secrets.token_urlsafe(9)
ALICE, BOB = "alice" + _secrets.token_hex(2), "bob" + _secrets.token_hex(2)

ENTRY_ID = "tag:google.com,2005:reader/item/000659e07aaee24d"
VALID_REF = encode_entry_ref(ENTRY_ID)

ENTRY = EntryListItem(
    entryRef=VALID_REF,
    title="科技爱好者周刊（第 409 期）",
    feedTitle="阮一峰的网络日志",
    author="阮一峰",
    url="http://example.com/weekly-409",
    publishedAt="2026-08-20T23:53:54Z",
    read=False,
    starred=False,
)

DETAIL = EntryDetail(
    entryRef=VALID_REF,
    title="科技爱好者周刊（第 409 期）",
    feedTitle="阮一峰的网络日志",
    author="阮一峰",
    url="http://example.com/weekly-409",
    publishedAt="2026-08-20T23:53:54Z",
    read=False,
    starred=False,
    contentText="这里是文章正文纯文本。",
    contentHtml="<p>这里是文章正文纯文本。</p><script>alert('x')</script>",
)


class RecordingAdapter:
    """Shared stub: records state writes so set-semantics is asserted
    against what FreshRSS would actually have received."""

    def __init__(self) -> None:
        self.state_writes: list[tuple[str, dict]] = []
        self.read_state: dict[str, dict] = {ENTRY_ID: {"read": False, "starred": False}}

    async def list_feeds(self):
        return []

    async def list_entries(self, *, view="all", feed_url=None, category_id=None, source_type=None, continuation=None):
        items = []
        fresh_read = self.read_state[ENTRY_ID]["read"]
        fresh_starred = self.read_state[ENTRY_ID]["starred"]
        items.append(
            EntryListItem(
                **{
                    **ENTRY.model_dump(),
                    "read": fresh_read,
                    "starred": fresh_starred,
                }
            )
        )
        return EntryPage(items=items, upstreamContinuation=None)

    async def get_entry(self, item_id: str) -> EntryDetail:
        return EntryDetail(
            **{
                **DETAIL.model_dump(),
                "read": self.read_state[item_id]["read"],
                "starred": self.read_state[item_id]["starred"],
            }
        )

    async def set_entry_state(self, item_id: str, *, read=None, starred=None):
        self.state_writes.append((item_id, {"read": read, "starred": starred}))
        current = self.read_state.setdefault(item_id, {"read": False, "starred": False})
        # FreshRSS semantics: explicit set, None = untouched.
        if read is not None:
            current["read"] = read
        if starred is not None:
            current["starred"] = starred


@pytest.fixture()
def session_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    return tmp_path


def _create_account(db_path, username: str, password: str) -> None:
    import asyncio

    database = Database(db_path / "lumi.sqlite")

    async def run():
        await database.migrate()
        await AccountsStore(database).create_user(
            username=username, password_hash=hash_password(password), role="member"
        )

    asyncio.run(run())


@pytest.fixture()
def two_accounts(session_env):
    _create_account(session_env, ALICE, PASSWORD)
    _create_account(session_env, BOB, PASSWORD)
    return session_env


def _native_login(client: TestClient, username: str, password: str):
    """Native profile: URLSession sends no Origin header by default."""
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_version_probe_is_public(two_accounts):
    with TestClient(app) as client:
        response = client.get("/api/v1/version")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"version", "commit", "apiVersion"}
    assert body["version"].count(".") >= 1  # semver-shaped


def test_native_cookie_login_session_logout_roundtrip(two_accounts):
    adapter = RecordingAdapter()
    try:
        with TestClient(app, base_url="http://lumirss.test") as client:
            app.state.freshrss_adapter = adapter
            # Login without an Origin header (native URLSession profile).
            login = _native_login(client, ALICE, PASSWORD)
            assert login.status_code == 200
            assert login.json()["authenticated"] is True
            cookie = login.cookies.get("lumirss_session")
            assert cookie, "plain-mode session cookie must be set for native clients"

            # Identity comes from the server, not the client.
            probe = client.get("/api/v1/auth/session")
            assert probe.status_code == 200
            assert probe.json()["username"] == ALICE

            # Vertical reading loop: list → detail → state → readback.
            listing = client.get("/api/v1/entries")
            assert listing.status_code == 200
            assert listing.json()["items"][0]["entryRef"] == VALID_REF

            detail = client.get(f"/api/v1/entries/{VALID_REF}")
            assert detail.status_code == 200
            body = detail.json()
            assert body["contentHtml"].startswith("<p>")
            assert body["read"] is False

            # SET semantics: read=true twice must never flip back.
            first = client.patch(f"/api/v1/entries/{VALID_REF}/state", json={"read": True})
            assert first.status_code == 204
            second = client.patch(f"/api/v1/entries/{VALID_REF}/state", json={"read": True})
            assert second.status_code == 204
            assert [w for _, w in adapter.state_writes] == [
                {"read": True, "starred": None},
                {"read": True, "starred": None},
            ], "every write carries read=true — set, not toggle"

            # Star + unstar with explicit values.
            client.patch(f"/api/v1/entries/{VALID_REF}/state", json={"starred": True})
            client.patch(f"/api/v1/entries/{VALID_REF}/state", json={"starred": False})

            # State readback is consistent for the same client.
            after = client.get("/api/v1/entries")
            item = after.json()["items"][0]
            assert item["read"] is True
            assert item["starred"] is False

            # Logout revokes server-side: the SAME cookie stops working.
            client.post("/api/v1/auth/logout")
            post_logout = client.get("/api/v1/auth/session")
            assert post_logout.json()["authenticated"] is False
            entries_after = client.get("/api/v1/entries")
            assert entries_after.status_code == 401
    finally:
        app.state.freshrss_adapter = None


def test_second_account_identity_isolation(two_accounts):
    adapter = RecordingAdapter()
    try:
        with TestClient(app, base_url="http://lumirss.test") as client:
            app.state.freshrss_adapter = adapter
            assert _native_login(client, ALICE, PASSWORD).status_code == 200
            alice_cookie = client.cookies.get("lumirss_session")

            # A second client (separate cookie jar) logs in as bob.
            with TestClient(app, base_url="http://lumirss.test") as other:
                assert _native_login(other, BOB, PASSWORD).status_code == 200
                probe = other.get("/api/v1/auth/session")
                assert probe.json()["username"] == BOB
                # Bob has no FreshRSS binding yet (honest pending state),
                # so his timeline is a clean 503 upstream_unconfigured —
                # NOT alice's data leaking through a shared adapter.
                listing = other.get("/api/v1/entries")
                assert listing.status_code == 503
                assert "error" in listing.json()

            # Alice's cookie still maps to alice.
            assert client.get("/api/v1/auth/session").json()["username"] == ALICE
            assert alice_cookie
    finally:
        app.state.freshrss_adapter = None


def test_wrong_password_is_generic_401(two_accounts):
    with TestClient(app, base_url="http://lumirss.test") as client:
        response = _native_login(client, ALICE, "definitely-not-" + PASSWORD)
        assert response.status_code == 401
        assert response.json()["error"]["type"] == "invalid_credentials"
