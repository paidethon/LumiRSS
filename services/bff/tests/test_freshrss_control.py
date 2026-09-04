"""0013 Gate 1 — FreshRSSControlAdapter protocol tests against a mocked
FreshRSS 1.29.1 (behaviors verified live; see adapter module docstring).

MockTransport asserts the exact form bodies that reach FreshRSS. Every fake
value here is clearly test data; no real credentials are used.
"""

import urllib.parse

import httpx
import pytest

from lumirss.adapters.freshrss import (
    AuthenticationError,
    FreshRSSAdapter,
    UpstreamError,
)
from lumirss.adapters.freshrss_control import (
    Category,
    CategoryLabelConflict,
    CategoryNotFound,
    DefaultCategoryImmutable,
    FeedRejectedError,
    FreshRSSControlAdapter,
    InvalidCategoryLabel,
    InvalidCategoryReference,
    InvalidFeedUrl,
    Subscription,
    SubscriptionConflict,
    SubscriptionNotFound,
)
from lumirss.config import FreshRSSSettings
from lumirss.subscriptionref import InvalidSubscriptionReference

import secrets as _secrets
# 动态生成的假凭据（非真实 secret；安全扫描要求无凭据形状字面量）
FAKE_SECRET = "fake-test-" + _secrets.token_urlsafe(8)

FAKE_TOKEN = "fake-test-token-0013"
FAKE_ACTION_TOKEN = "fake-action-token-0013"
BASE_URL = "http://freshrss-test.local"
DEFAULT_CATEGORY = "user/-/label/未分类"  # localized default category (zh-cn)
EXISTING_URL = "https://example.com/existing.xml"
NEW_URL = "https://example.com/new.xml"


def make_settings() -> FreshRSSSettings:
    return FreshRSSSettings(
        _env_file=None,
        FRESHRSS_BASE_URL=BASE_URL,
        FRESHRSS_USERNAME="test-user",
        FRESHRSS_API_PASSWORD=FAKE_SECRET,
    )


class FakeFreshRSS:
    """Stateful mock of the four greader endpoints the control plane uses."""

    def __init__(self) -> None:
        self.subscriptions: list[dict] = [
            {
                "id": "feed/7",
                "title": "Existing Feed",
                "url": EXISTING_URL,
                "categories": [{"id": DEFAULT_CATEGORY, "label": "未分类"}],
            }
        ]
        self.folders: list[str] = [DEFAULT_CATEGORY.removeprefix("user/-/label/")]
        # per-request answers: "OK"-like body or an int HTTP status, in order
        self.edit_responses: list[str | int] = []
        self.rename_responses: list[str | int] = []
        self.apply_rename = True
        self.apply_subscribe = True
        # Gate 3: edit answers OK but the move is not visible afterwards
        self.move_not_applied = False
        self.requests: list[httpx.Request] = []
        self.logins = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/accounts/ClientLogin"):
            self.logins += 1
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        if path.endswith("/reader/api/0/token"):
            return httpx.Response(200, text=FAKE_ACTION_TOKEN)
        if path.endswith("/reader/api/0/subscription/list"):
            return httpx.Response(200, json={"subscriptions": self.subscriptions})
        if path.endswith("/reader/api/0/tag/list"):
            return httpx.Response(
                200,
                json={
                    "tags": [
                        {"id": "user/-/state/com.google/starred"},
                        {"id": "user/-/label/标签", "type": "tag"},
                        *(
                            {"id": f"user/-/label/{name}", "type": "folder"}
                            for name in self.folders
                        ),
                    ]
                },
            )
        if path.endswith("/reader/api/0/subscription/edit"):
            fields = dict(urllib.parse.parse_qsl(request.read().decode("utf-8")))
            answer = self.edit_responses.pop(0) if self.edit_responses else "OK"
            if fields.get("ac") == "subscribe" and self.apply_subscribe:
                self.subscriptions.append(
                    {
                        "id": "feed/9",
                        "title": fields.get("t") or "New Feed",
                        "url": fields.get("s", "").removeprefix("feed/"),
                        "categories": [
                            {
                                "id": fields["a"],
                                "label": fields["a"].removeprefix("user/-/label/"),
                            }
                        ]
                        if fields.get("a")
                        else [],
                    }
                )
            elif fields.get("ac") == "unsubscribe":
                self.subscriptions = [
                    s for s in self.subscriptions if s["id"] != fields.get("s")
                ]
            elif (
                fields.get("ac") == "edit"
                and fields.get("s") in {s["id"] for s in self.subscriptions}
                and fields.get("a")
                and not self.move_not_applied
            ):
                # ac=edit + a= moves (and auto-creates) the category
                target = fields["a"]
                for subscription in self.subscriptions:
                    if subscription["id"] == fields["s"]:
                        subscription["categories"] = [
                            {
                                "id": target,
                                "label": target.removeprefix("user/-/label/"),
                            }
                        ]
                if target.removeprefix("user/-/label/") not in self.folders:
                    self.folders.append(target.removeprefix("user/-/label/"))
            return self._answer(answer)
        if path.endswith("/reader/api/0/rename-tag"):
            fields = dict(urllib.parse.parse_qsl(request.read().decode("utf-8")))
            answer = self.rename_responses.pop(0) if self.rename_responses else "OK"
            if isinstance(answer, str) and self.apply_rename:
                old = fields["s"].removeprefix("user/-/label/")
                new = fields["dest"].removeprefix("user/-/label/")
                if old != new:  # a no-op probe must not mutate state
                    self.folders = [new if name == old else name for name in self.folders]
            return self._answer(answer)
        raise AssertionError(f"unexpected endpoint: {path}")

    @staticmethod
    def _answer(answer: str | int) -> httpx.Response:
        if isinstance(answer, int):
            return httpx.Response(answer, text="Bad Request!")
        return httpx.Response(200, text=answer)

    def posts(self, suffix: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.endswith(suffix)]


def make_control(handler) -> FreshRSSControlAdapter:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    )
    adapter = FreshRSSAdapter(client, make_settings())
    return FreshRSSControlAdapter(adapter)


def form_fields(request: httpx.Request) -> list[tuple[str, str]]:
    return urllib.parse.parse_qsl(request.read().decode("utf-8"))


# --- list operations -------------------------------------------------------


@pytest.mark.anyio
async def test_list_subscriptions_maps_stream_ids_and_categories():
    fake = FakeFreshRSS()
    control = make_control(fake.handler)

    subscriptions = await control.list_subscriptions()

    assert subscriptions == [
        Subscription(
            stream_id="feed/7",
            title="Existing Feed",
            feed_url=EXISTING_URL,
            category_id=DEFAULT_CATEGORY,
            category_label="未分类",
        )
    ]
    assert subscriptions[0].subscription_ref.startswith("s1.")


@pytest.mark.anyio
async def test_list_subscriptions_without_category_is_tolerated():
    fake = FakeFreshRSS()
    fake.subscriptions[0]["categories"] = []
    control = make_control(fake.handler)

    subscriptions = await control.list_subscriptions()

    assert subscriptions[0].category_id is None
    assert subscriptions[0].category_label is None


@pytest.mark.anyio
async def test_list_subscriptions_malformed_entry_is_upstream_error():
    fake = FakeFreshRSS()
    fake.subscriptions[0].pop("id")
    control = make_control(fake.handler)

    with pytest.raises(UpstreamError):
        await control.list_subscriptions()


@pytest.mark.anyio
async def test_list_categories_returns_folders_only():
    fake = FakeFreshRSS()
    fake.folders.append("技术")
    control = make_control(fake.handler)

    categories = await control.list_categories()

    assert categories == [
        Category(category_id=DEFAULT_CATEGORY, label="未分类"),
        Category(category_id="user/-/label/技术", label="技术"),
    ]


# --- subscribe -------------------------------------------------------------


@pytest.mark.anyio
async def test_subscribe_posts_protocol_fields_and_returns_confirmed_sub():
    fake = FakeFreshRSS()
    fake.folders.append("技术")
    control = make_control(fake.handler)

    created = await control.subscribe(
        NEW_URL, category_id="user/-/label/技术", title="  My Feed  "
    )

    edit = fake.posts("/subscription/edit")[-1]
    fields = form_fields(edit)
    assert ("ac", "subscribe") in fields
    assert ("s", f"feed/{NEW_URL}") in fields
    assert ("t", "My Feed") in fields  # stripped title
    assert ("a", "user/-/label/技术") in fields
    assert ("T", FAKE_ACTION_TOKEN) in fields
    # Server-confirmed: the returned subscription comes from the re-read.
    assert created == Subscription(
        stream_id="feed/9",
        title="My Feed",
        feed_url=NEW_URL,
        category_id="user/-/label/技术",
        category_label="技术",
    )


@pytest.mark.anyio
async def test_subscribe_duplicate_is_conflict_without_any_write():
    fake = FakeFreshRSS()
    control = make_control(fake.handler)

    with pytest.raises(SubscriptionConflict):
        await control.subscribe(EXISTING_URL)

    assert fake.posts("/subscription/edit") == []


@pytest.mark.anyio
async def test_subscribe_non_http_url_is_rejected_before_any_request():
    fake = FakeFreshRSS()
    control = make_control(fake.handler)

    with pytest.raises(InvalidFeedUrl):
        await control.subscribe("ftp://example.com/feed.xml")

    assert fake.requests == []


@pytest.mark.anyio
async def test_subscribe_unknown_category_is_not_found_without_write():
    fake = FakeFreshRSS()
    control = make_control(fake.handler)

    with pytest.raises(CategoryNotFound):
        await control.subscribe(NEW_URL, category_id="user/-/label/NoSuch")

    assert fake.posts("/subscription/edit") == []


@pytest.mark.anyio
async def test_subscribe_upstream_400_is_feed_rejected_without_secret_leak():
    fake = FakeFreshRSS()
    fake.edit_responses.append(400)
    control = make_control(fake.handler)

    with pytest.raises(FeedRejectedError) as exc_info:
        await control.subscribe(NEW_URL)

    assert FAKE_SECRET not in str(exc_info.value)


@pytest.mark.anyio
async def test_subscribe_accepted_but_invisible_is_upstream_error():
    fake = FakeFreshRSS()
    fake.apply_subscribe = False  # edit answers OK but nothing is stored
    control = make_control(fake.handler)

    with pytest.raises(UpstreamError):
        await control.subscribe(NEW_URL)


# --- unsubscribe -----------------------------------------------------------


@pytest.mark.anyio
async def test_unsubscribe_posts_stream_id():
    fake = FakeFreshRSS()
    control = make_control(fake.handler)

    await control.unsubscribe("feed/7")

    fields = form_fields(fake.posts("/subscription/edit")[-1])
    assert ("ac", "unsubscribe") in fields
    assert ("s", "feed/7") in fields


@pytest.mark.anyio
async def test_unsubscribe_unknown_stream_id_is_not_found_without_write():
    fake = FakeFreshRSS()
    control = make_control(fake.handler)

    with pytest.raises(SubscriptionNotFound):
        await control.unsubscribe("feed/999")

    assert fake.posts("/subscription/edit") == []


@pytest.mark.anyio
async def test_unsubscribe_malformed_stream_id_is_invalid_reference():
    fake = FakeFreshRSS()
    control = make_control(fake.handler)

    with pytest.raises(InvalidSubscriptionReference):
        await control.unsubscribe("tag:google.com,2005:reader/feed/7")

    assert fake.requests == []


@pytest.mark.anyio
async def test_unsubscribe_upstream_400_is_mapped_to_not_found():
    fake = FakeFreshRSS()
    fake.edit_responses.append(400)
    control = make_control(fake.handler)

    with pytest.raises(SubscriptionNotFound):
        await control.unsubscribe("feed/7")


# --- move category ---------------------------------------------------------


@pytest.mark.anyio
async def test_move_category_posts_edit_with_add_stream():
    fake = FakeFreshRSS()
    fake.folders.append("技术")
    control = make_control(fake.handler)

    await control.move_category("feed/7", "user/-/label/技术")

    fields = form_fields(fake.posts("/subscription/edit")[-1])
    assert ("ac", "edit") in fields
    assert ("s", "feed/7") in fields
    assert ("a", "user/-/label/技术") in fields


@pytest.mark.anyio
async def test_move_category_unknown_category_is_not_found_without_write():
    fake = FakeFreshRSS()
    control = make_control(fake.handler)

    with pytest.raises(CategoryNotFound):
        await control.move_category("feed/7", "user/-/label/NoSuch")

    assert fake.posts("/subscription/edit") == []


@pytest.mark.anyio
async def test_move_category_unknown_subscription_is_not_found():
    fake = FakeFreshRSS()
    fake.folders.append("技术")
    control = make_control(fake.handler)

    with pytest.raises(SubscriptionNotFound):
        await control.move_category("feed/999", "user/-/label/技术")


@pytest.mark.anyio
async def test_move_category_malformed_category_id_is_invalid_reference():
    fake = FakeFreshRSS()
    control = make_control(fake.handler)

    with pytest.raises(InvalidCategoryReference):
        await control.move_category("feed/7", "技术")

    assert fake.requests == []


# --- move to a NEW category (0013 Gate 3 create-category path) --------------


@pytest.mark.anyio
async def test_move_to_new_category_posts_edit_and_creates_folder():
    """Creating a category IS moving a feed into a not-yet-existing one —
    subscription/edit auto-creates the a= category (verified live).
    The fake mirrors that: the feed's category changes to the new label."""
    fake = FakeFreshRSS()
    control = make_control(fake.handler)

    await control.move_to_new_category("feed/7", "AI")

    fields = form_fields(fake.posts("/subscription/edit")[-1])
    assert ("ac", "edit") in fields
    assert ("s", "feed/7") in fields
    assert ("a", "user/-/label/AI") in fields
    assert ("T", FAKE_ACTION_TOKEN) in fields
    # the fake applies the move (see FakeFreshRSS.edit handler)
    assert fake.subscriptions[0]["categories"] == [
        {"id": "user/-/label/AI", "label": "AI"}
    ]
    # server-confirmed: the new category is now visible in tag/list
    categories = await control.list_categories()
    assert Category(category_id="user/-/label/AI", label="AI") in categories


@pytest.mark.anyio
async def test_move_to_new_category_taken_label_is_conflict_without_write():
    fake = FakeFreshRSS()
    fake.folders.append("技术")
    control = make_control(fake.handler)

    with pytest.raises(CategoryLabelConflict):
        await control.move_to_new_category("feed/7", "技术")

    assert fake.posts("/subscription/edit") == []


@pytest.mark.anyio
async def test_move_to_new_category_reserved_label_is_conflict():
    fake = FakeFreshRSS()
    control = make_control(fake.handler)

    with pytest.raises(CategoryLabelConflict):
        await control.move_to_new_category("feed/7", "Uncategorized")

    assert fake.posts("/subscription/edit") == []


@pytest.mark.anyio
async def test_move_to_new_category_localized_default_label_is_conflict():
    """Renaming/creating into the localized default name would mint a real
    category that displays like the default one — pre-checked and refused
    (the live trap, 0013 Gate 1)."""
    fake = FakeFreshRSS()
    control = make_control(fake.handler)

    with pytest.raises(CategoryLabelConflict):
        await control.move_to_new_category("feed/7", "未分类")

    assert fake.posts("/subscription/edit") == []


@pytest.mark.anyio
async def test_move_to_new_category_unknown_subscription_is_not_found():
    fake = FakeFreshRSS()
    control = make_control(fake.handler)

    with pytest.raises(SubscriptionNotFound):
        await control.move_to_new_category("feed/999", "AI")

    assert fake.posts("/subscription/edit") == []


@pytest.mark.anyio
@pytest.mark.parametrize("bad_label", ["", "   ", "a/b", "x" * 129])
async def test_move_to_new_category_invalid_labels_rejected_before_requests(
    bad_label,
):
    fake = FakeFreshRSS()
    control = make_control(fake.handler)

    with pytest.raises(InvalidCategoryLabel):
        await control.move_to_new_category("feed/7", bad_label)

    assert fake.requests == []


@pytest.mark.anyio
async def test_move_to_new_category_silent_noop_is_upstream_error():
    """Upstream can answer OK while the move changed nothing (unchecked
    SQL) — the post-check re-read must catch it."""
    fake = FakeFreshRSS()
    fake.move_not_applied = True  # see FakeFreshRSS.edit handler
    control = make_control(fake.handler)

    with pytest.raises(UpstreamError):
        await control.move_to_new_category("feed/7", "AI")


# --- rename category -------------------------------------------------------


@pytest.mark.anyio
async def test_rename_category_probes_default_then_renames_with_postcheck():
    fake = FakeFreshRSS()
    fake.folders.append("技术")
    control = make_control(fake.handler)

    await control.rename_category("user/-/label/技术", "Tech")

    renames = fake.posts("/rename-tag")
    assert len(renames) == 2  # no-op probe, then the real rename
    probe_fields = form_fields(renames[0])
    real_fields = form_fields(renames[1])
    assert ("s", "user/-/label/技术") in probe_fields
    assert ("dest", "user/-/label/技术") in probe_fields
    assert ("s", "user/-/label/技术") in real_fields
    assert ("dest", "user/-/label/Tech") in real_fields
    assert ("T", FAKE_ACTION_TOKEN) in real_fields


@pytest.mark.anyio
async def test_rename_category_default_category_is_immutable():
    """The default category's visible name never matches its DB name, so the
    no-op probe gets a 400 — and NO real rename attempt is made."""
    fake = FakeFreshRSS()
    fake.rename_responses.append(400)
    control = make_control(fake.handler)

    with pytest.raises(DefaultCategoryImmutable):
        await control.rename_category(DEFAULT_CATEGORY, "Tech")

    assert len(fake.posts("/rename-tag")) == 1  # probe only


@pytest.mark.anyio
async def test_rename_category_unknown_category_is_not_found():
    fake = FakeFreshRSS()
    control = make_control(fake.handler)

    with pytest.raises(CategoryNotFound):
        await control.rename_category("user/-/label/NoSuch", "Tech")

    assert fake.posts("/rename-tag") == []


@pytest.mark.anyio
async def test_rename_category_taken_label_is_conflict_without_write():
    fake = FakeFreshRSS()
    fake.folders.append("技术")
    control = make_control(fake.handler)

    with pytest.raises(CategoryLabelConflict):
        await control.rename_category(DEFAULT_CATEGORY, "技术")

    assert fake.posts("/rename-tag") == []


@pytest.mark.anyio
async def test_rename_category_reserved_label_is_conflict():
    fake = FakeFreshRSS()
    fake.folders.append("技术")
    control = make_control(fake.handler)

    with pytest.raises(CategoryLabelConflict):
        await control.rename_category("user/-/label/技术", "Uncategorized")


@pytest.mark.anyio
async def test_rename_category_silent_noop_is_upstream_error():
    """FreshRSS can answer OK while applying nothing (UNIQUE(name) / a
    same-named tag blocks the SQL UPDATE) — the post-check must catch it."""
    fake = FakeFreshRSS()
    fake.folders.append("技术")
    fake.apply_rename = False  # rename-tag answers OK but changes nothing
    control = make_control(fake.handler)

    with pytest.raises(UpstreamError):
        await control.rename_category("user/-/label/技术", "Tech")


@pytest.mark.anyio
@pytest.mark.parametrize("bad_label", ["", "   ", "a/b", "x" * 129])
async def test_rename_category_invalid_labels_are_rejected_before_requests(
    bad_label,
):
    fake = FakeFreshRSS()
    fake.folders.append("技术")
    control = make_control(fake.handler)

    with pytest.raises(InvalidCategoryLabel):
        await control.rename_category("user/-/label/技术", bad_label)

    assert fake.requests == []


# --- shared session / auth retry -------------------------------------------


@pytest.mark.anyio
async def test_control_shares_session_tokens_with_read_adapter():
    """One ClientLogin total: the read adapter logs in, the control adapter
    reuses the cached auth token (no duplicated login state)."""
    fake = FakeFreshRSS()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(fake.handler), trust_env=False
    )
    read_adapter = FreshRSSAdapter(client, make_settings())
    control = FreshRSSControlAdapter(read_adapter)

    await read_adapter.list_feeds()
    await control.list_subscriptions()
    await control.list_categories()

    assert fake.logins == 1
    await client.aclose()


@pytest.mark.anyio
async def test_control_relogin_once_on_stale_auth_token():
    fake = FakeFreshRSS()
    stale = {"rejected": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if (
            request.url.path.endswith("/reader/api/0/tag/list")
            and not stale["rejected"]
        ):
            stale["rejected"] = True
            return httpx.Response(401)
        return fake.handler(request)

    control = make_control(handler)

    categories = await control.list_categories()

    assert categories  # retried once with a fresh login
    assert fake.logins == 2


@pytest.mark.anyio
async def test_control_persistent_401_raises_authentication_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        return httpx.Response(401)

    control = make_control(handler)

    with pytest.raises(AuthenticationError):
        await control.list_categories()
