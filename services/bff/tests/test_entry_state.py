"""Tests I–Q — Action Token, edit-tag mapping, 401 recovery, PATCH route.

MockTransport asserts the exact form body that reaches FreshRSS (including
repeated a=/r= fields). Every fake value is clearly test data; the action
token is an obvious fake, never a real secret.
"""

import urllib.parse

import httpx
import pytest
from fastapi.testclient import TestClient

from lumirss.adapters.freshrss import (
    AuthenticationError,
    FreshRSSAdapter,
    UpstreamError,
)
from lumirss.config import FreshRSSSettings
from lumirss.entryref import encode_entry_ref
from lumirss.main import app

FAKE_TOKEN = "fake-test-token-0004"
FAKE_ACTION_TOKEN = "fake-action-token-0004"
BASE_URL = "http://freshrss-test.local"
ITEM_ID = "tag:google.com,2005:reader/item/000659e07aaee24d"
VALID_REF = encode_entry_ref(ITEM_ID)
READ_MARKER = "user/-/state/com.google/read"
STARRED_MARKER = "user/-/state/com.google/starred"


def make_settings() -> FreshRSSSettings:
    return FreshRSSSettings(
        _env_file=None,
        FRESHRSS_BASE_URL=BASE_URL,
        FRESHRSS_USERNAME="test-user",
        FRESHRSS_API_PASSWORD="fake-test-password",
    )


def make_adapter(handler) -> tuple[FreshRSSAdapter, list[httpx.Request]]:
    requested: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(recording_handler), trust_env=False)
    return FreshRSSAdapter(client, make_settings()), requested


def ok_handler(
    token_responses: list[str] | None = None,
    edit_bodies: list[str] | None = None,
) -> httpx.Response:
    """Handler state holder: token/edit responses served in order."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        if path.endswith("/token"):
            value = token_responses.pop(0) if token_responses else FAKE_ACTION_TOKEN
            return httpx.Response(200, text=value)
        if path.endswith("/edit-tag"):
            body = edit_bodies.pop(0) if edit_bodies else "OK"
            return httpx.Response(200, text=body)
        raise AssertionError(f"unexpected endpoint: {path}")

    return handler


def form_fields(request: httpx.Request) -> list[tuple[str, str]]:
    return urllib.parse.parse_qsl(request.read().decode("utf-8"))


# --- Test I — action token fetch + cache ------------------------------------


@pytest.mark.anyio
async def test_action_token_is_fetched_then_cached_in_memory():
    token_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        if request.url.path.endswith("/token"):
            token_calls.append("token")
            return httpx.Response(200, text=f"{FAKE_ACTION_TOKEN}\n")
        return httpx.Response(200, text="OK")

    adapter, _ = make_adapter(handler)

    await adapter.set_entry_state(ITEM_ID, read=True)
    await adapter.set_entry_state(ITEM_ID, read=False)

    assert len(token_calls) == 1  # second write reuses the cached token
    assert adapter._action_token == FAKE_ACTION_TOKEN  # memory only


@pytest.mark.anyio
async def test_empty_action_token_is_upstream_error_and_no_edit_tag():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        if request.url.path.endswith("/token"):
            return httpx.Response(200, text="")
        raise AssertionError("edit-tag must not be called")

    adapter, _ = make_adapter(handler)

    with pytest.raises(UpstreamError):
        await adapter.set_entry_state(ITEM_ID, read=True)
    assert adapter._action_token is None  # nothing cached


@pytest.mark.anyio
async def test_whitespace_action_token_is_upstream_error_and_no_edit_tag():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        if request.url.path.endswith("/token"):
            return httpx.Response(200, text="   \n  ")
        raise AssertionError("edit-tag must not be called")

    adapter, _ = make_adapter(handler)

    with pytest.raises(UpstreamError):
        await adapter.set_entry_state(ITEM_ID, read=True)


@pytest.mark.anyio
async def test_x_action_token_is_upstream_error_and_no_edit_tag():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        if request.url.path.endswith("/token"):
            return httpx.Response(200, text="x")
        raise AssertionError("edit-tag must not be called")

    adapter, _ = make_adapter(handler)

    with pytest.raises(UpstreamError):
        await adapter.set_entry_state(ITEM_ID, read=True)


# --- Test J / K — mark read / unread ----------------------------------------


@pytest.mark.anyio
async def test_mark_read_sends_add_read_with_action_token():
    adapter, requested = make_adapter(ok_handler())

    await adapter.set_entry_state(ITEM_ID, read=True)

    edit = requested[-1]
    assert edit.url.path.endswith("/edit-tag")
    fields = form_fields(edit)
    assert ("T", FAKE_ACTION_TOKEN) in fields
    assert ("i", ITEM_ID) in fields
    assert ("a", READ_MARKER) in fields
    assert ("r", READ_MARKER) not in fields


@pytest.mark.anyio
async def test_mark_unread_sends_remove_read():
    adapter, requested = make_adapter(ok_handler())

    await adapter.set_entry_state(ITEM_ID, read=False)

    fields = form_fields(requested[-1])
    assert ("r", READ_MARKER) in fields
    assert ("a", READ_MARKER) not in fields


# --- Test L — star / unstar --------------------------------------------------


@pytest.mark.anyio
async def test_star_sends_add_starred():
    adapter, requested = make_adapter(ok_handler())

    await adapter.set_entry_state(ITEM_ID, starred=True)

    fields = form_fields(requested[-1])
    assert ("a", STARRED_MARKER) in fields
    assert ("r", STARRED_MARKER) not in fields


@pytest.mark.anyio
async def test_unstar_sends_remove_starred():
    adapter, requested = make_adapter(ok_handler())

    await adapter.set_entry_state(ITEM_ID, starred=False)

    fields = form_fields(requested[-1])
    assert ("r", STARRED_MARKER) in fields
    assert ("a", STARRED_MARKER) not in fields


# --- Test M — combined state in ONE edit-tag --------------------------------


@pytest.mark.anyio
async def test_combined_read_true_starred_true_sends_two_a_fields_in_one_request():
    adapter, requested = make_adapter(ok_handler())

    await adapter.set_entry_state(ITEM_ID, read=True, starred=True)

    edit_requests = [r for r in requested if r.url.path.endswith("/edit-tag")]
    assert len(edit_requests) == 1  # exactly one edit-tag
    fields = form_fields(edit_requests[0])
    assert fields.count(("a", READ_MARKER)) == 1
    assert fields.count(("a", STARRED_MARKER)) == 1
    assert ("r", READ_MARKER) not in fields
    assert ("r", STARRED_MARKER) not in fields


@pytest.mark.anyio
async def test_combined_read_false_starred_false_sends_two_r_fields_in_one_request():
    adapter, requested = make_adapter(ok_handler())

    await adapter.set_entry_state(ITEM_ID, read=False, starred=False)

    edit_requests = [r for r in requested if r.url.path.endswith("/edit-tag")]
    assert len(edit_requests) == 1
    fields = form_fields(edit_requests[0])
    assert fields.count(("r", READ_MARKER)) == 1
    assert fields.count(("r", STARRED_MARKER)) == 1
    assert ("a", READ_MARKER) not in fields
    assert ("a", STARRED_MARKER) not in fields


@pytest.mark.anyio
async def test_mixed_combined_read_true_starred_false():
    adapter, requested = make_adapter(ok_handler())

    await adapter.set_entry_state(ITEM_ID, read=True, starred=False)

    edit_requests = [r for r in requested if r.url.path.endswith("/edit-tag")]
    assert len(edit_requests) == 1
    fields = form_fields(edit_requests[0])
    assert ("a", READ_MARKER) in fields
    assert ("r", STARRED_MARKER) in fields


# --- edit-tag success body validation ---------------------------------------


@pytest.mark.anyio
async def test_edit_tag_unexpected_body_is_upstream_error():
    adapter, _ = make_adapter(ok_handler(edit_bodies=["NOT-OK"]))

    with pytest.raises(UpstreamError):
        await adapter.set_entry_state(ITEM_ID, read=True)


@pytest.mark.anyio
async def test_edit_tag_non_200_is_upstream_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        if request.url.path.endswith("/token"):
            return httpx.Response(200, text=FAKE_ACTION_TOKEN)
        return httpx.Response(500)

    adapter, _ = make_adapter(handler)

    with pytest.raises(UpstreamError):
        await adapter.set_entry_state(ITEM_ID, read=True)


# --- Test P — write 401 recovery ---------------------------------------------


@pytest.mark.anyio
async def test_edit_tag_401_recovers_once_with_new_tokens():
    """First edit-tag 401 → clear both tokens → re-login → new action token
    → retry exactly once. Asserts the retried request carries fresh tokens."""
    events: list[str] = []
    logins: list[str] = []
    tokens: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/accounts/ClientLogin"):
            logins.append("login")
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        if path.endswith("/token"):
            tokens.append("token")
            return httpx.Response(200, text=FAKE_ACTION_TOKEN)
        # edit-tag: reject the first attempt (stale tokens), accept the second
        events.append("edit")
        return httpx.Response(401) if len(events) == 1 else httpx.Response(200, text="OK")

    adapter, _ = make_adapter(handler)

    await adapter.set_entry_state(ITEM_ID, read=True)

    assert events == ["edit", "edit"]  # exactly one retry
    assert len(logins) == 2  # re-login happened
    assert len(tokens) == 2  # fresh action token was fetched


@pytest.mark.anyio
async def test_edit_tag_401_twice_raises_authentication_error():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        if path.endswith("/token"):
            return httpx.Response(200, text=FAKE_ACTION_TOKEN)
        return httpx.Response(401)  # always reject the write

    adapter, _ = make_adapter(handler)

    with pytest.raises(AuthenticationError):
        await adapter.set_entry_state(ITEM_ID, read=True)


@pytest.mark.anyio
async def test_token_endpoint_401_recovers_once_via_relogin():
    """GET /token 401 → clear both tokens → ClientLogin → retry /token once."""
    token_calls: list[str] = []
    login_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/accounts/ClientLogin"):
            login_calls.append("login")
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        if path.endswith("/token"):
            token_calls.append("token")
            return httpx.Response(401) if len(token_calls) == 1 else httpx.Response(200, text=FAKE_ACTION_TOKEN)
        return httpx.Response(200, text="OK")

    adapter, _ = make_adapter(handler)

    await adapter.set_entry_state(ITEM_ID, read=True)

    assert len(token_calls) == 2  # retried exactly once
    assert len(login_calls) == 2  # re-login before the retry


@pytest.mark.anyio
async def test_stale_auth_token_invalidates_cached_action_token():
    """A fresh login must never be paired with the old action token."""
    # Warm both caches, then break the auth token and the action token at once.
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/accounts/ClientLogin"):
            calls.append("login")
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        if path.endswith("/token"):
            calls.append("token")
            return httpx.Response(200, text=FAKE_ACTION_TOKEN)
        calls.append("edit")
        # First edit uses stale tokens → 401; second edit succeeds.
        return httpx.Response(401) if calls.count("edit") == 1 else httpx.Response(200, text="OK")

    adapter, _ = make_adapter(handler)

    await adapter.set_entry_state(ITEM_ID, read=True)
    assert adapter._auth_token == FAKE_TOKEN
    assert adapter._action_token == FAKE_ACTION_TOKEN

    # Simulate credential change: read path 401 clears both tokens together.
    adapter._clear_tokens()
    assert adapter._auth_token is None
    assert adapter._action_token is None


# --- Test N / O / Q — PATCH route ---------------------------------------------


class FakeStateAdapter:
    def __init__(self, error=None) -> None:
        self.calls: list[tuple[str, bool | None, bool | None]] = []
        self.error = error

    async def list_feeds(self):
        return []

    async def list_entries(self, *, view="all", feed_url=None, category_id=None, source_type=None, continuation=None):
        raise AssertionError("not under test")

    async def get_entry(self, item_id: str):
        raise AssertionError("not under test")

    async def set_entry_state(self, item_id, *, read=None, starred=None):
        self.calls.append((item_id, read, starred))
        if self.error is not None:
            raise self.error
        return None


def patch_state(fake, entry_ref, json_body):
    try:
        with TestClient(app) as client:
            app.state.freshrss_adapter = fake
            return client.patch(
                f"/api/v1/entries/{entry_ref}/state", json=json_body
            )
    finally:
        app.state.freshrss_adapter = None


def test_state_route_success_is_204():  # Test Q
    fake = FakeStateAdapter()
    response = patch_state(fake, VALID_REF, {"read": True})

    assert response.status_code == 204
    assert response.content == b""
    assert fake.calls == [(ITEM_ID, True, None)]


def test_state_route_combined_body_reaches_adapter():
    fake = FakeStateAdapter()
    response = patch_state(fake, VALID_REF, {"read": True, "starred": False})

    assert response.status_code == 204
    assert fake.calls == [(ITEM_ID, True, False)]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"read": None},
        {"starred": None},
        {"read": None, "starred": None},
    ],
)
def test_state_route_invalid_bodies_are_422_without_freshrss(body):  # Test N
    fake = FakeStateAdapter()
    response = patch_state(fake, VALID_REF, body)

    assert response.status_code == 422
    assert fake.calls == []  # no /token, no edit-tag, nothing upstream


def test_state_route_non_bool_values_are_422():
    fake = FakeStateAdapter()
    response = patch_state(fake, VALID_REF, {"read": 1})  # strict bool: no coercion
    assert response.status_code == 422
    response = patch_state(fake, VALID_REF, {"read": "true"})
    assert response.status_code == 422
    assert fake.calls == []


def test_state_route_invalid_entry_ref_is_400_without_freshrss():  # Test O
    fake = FakeStateAdapter()
    response = patch_state(fake, "not-a-valid-ref", {"read": True})

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_entry_reference"
    assert fake.calls == []  # neither /token nor edit-tag was called


def test_state_route_maps_authentication_error():
    fake = FakeStateAdapter(error=AuthenticationError("FreshRSS rejected the credentials."))
    response = patch_state(fake, VALID_REF, {"read": True})

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "authentication_error"
