"""0013 Gate 1 — /api/v1/subscriptions + /api/v1/categories route wiring.

No real FreshRSS is contacted: a fake control adapter is injected onto
app.state, so these tests exercise the routes and error mapping only.
"""

from fastapi.testclient import TestClient

from lumirss.adapters.freshrss import AuthenticationError
from lumirss.adapters.freshrss_control import (
    Category,
    CategoryLabelConflict,
    DefaultCategoryImmutable,
    FeedRejectedError,
    Subscription,
    SubscriptionConflict,
    SubscriptionNotFound,
)
from lumirss.main import app
from lumirss.subscriptionref import encode_subscription_ref

EXISTING_REF = encode_subscription_ref("feed/7")
DEFAULT_CATEGORY = "user/-/label/未分类"


class FakeControlAdapter:
    def __init__(self, error=None) -> None:
        self.error = error
        self.calls: list[tuple] = []

    async def list_subscriptions(self):
        self.calls.append(("list_subscriptions",))
        if self.error is not None:
            raise self.error
        return [
            Subscription(
                stream_id="feed/7",
                title="Existing Feed",
                feed_url="https://example.com/existing.xml",
                category_id=DEFAULT_CATEGORY,
                category_label="未分类",
            ),
            Subscription(
                stream_id="feed/8",
                title="Uncategorized Feed",
                feed_url="https://example.com/none.xml",
            ),
        ]

    async def list_categories(self):
        self.calls.append(("list_categories",))
        if self.error is not None:
            raise self.error
        return [Category(category_id=DEFAULT_CATEGORY, label="未分类")]

    async def subscribe(self, feed_url, *, category_id=None, title=None):
        self.calls.append(("subscribe", feed_url, category_id, title))
        if self.error is not None:
            raise self.error
        return Subscription(
            stream_id="feed/9",
            title=title or "New Feed",
            feed_url=feed_url,
            category_id=category_id,
            category_label=(
                category_id.removeprefix("user/-/label/") if category_id else None
            ),
        )

    async def unsubscribe(self, stream_id):
        self.calls.append(("unsubscribe", stream_id))
        if self.error is not None:
            raise self.error

    async def move_category(self, stream_id, category_id):
        self.calls.append(("move_category", stream_id, category_id))
        if self.error is not None:
            raise self.error

    async def move_to_new_category(self, stream_id, label):
        self.calls.append(("move_to_new_category", stream_id, label))
        if self.error is not None:
            raise self.error

    async def rename_category(self, category_id, new_label):
        self.calls.append(("rename_category", category_id, new_label))
        if self.error is not None:
            raise self.error


def call(fake, method, path, **kwargs):
    try:
        with TestClient(app) as client:
            app.state.freshrss_control_adapter = fake
            return client.request(method, path, **kwargs)
    finally:
        app.state.freshrss_control_adapter = None


def test_subscriptions_route_returns_subscription_ref_shape():
    fake = FakeControlAdapter()
    response = call(fake, "GET", "/api/v1/subscriptions")

    assert response.status_code == 200
    body = response.json()
    assert body[0] == {
        "subscriptionRef": EXISTING_REF,
        "title": "Existing Feed",
        "feedUrl": "https://example.com/existing.xml",
        "category": {"id": DEFAULT_CATEGORY, "label": "未分类"},
    }
    assert body[1]["category"] is None


def test_categories_route_returns_id_and_label():
    fake = FakeControlAdapter()
    response = call(fake, "GET", "/api/v1/categories")

    assert response.status_code == 200
    assert response.json() == [{"id": DEFAULT_CATEGORY, "label": "未分类"}]


def test_create_subscription_returns_201_with_body():
    fake = FakeControlAdapter()
    response = call(
        fake,
        "POST",
        "/api/v1/subscriptions",
        json={
            "feedUrl": "https://example.com/new.xml",
            "categoryId": DEFAULT_CATEGORY,
            "title": "New Feed",
        },
    )

    assert response.status_code == 201
    assert response.json()["feedUrl"] == "https://example.com/new.xml"
    assert fake.calls == [
        ("subscribe", "https://example.com/new.xml", DEFAULT_CATEGORY, "New Feed")
    ]


def test_create_subscription_conflict_is_409():
    fake = FakeControlAdapter(error=SubscriptionConflict("Already subscribed."))
    response = call(
        fake, "POST", "/api/v1/subscriptions", json={"feedUrl": "https://x.example.xml"}
    )

    assert response.status_code == 409
    assert response.json()["error"]["type"] == "subscription_conflict"


def test_create_subscription_feed_rejected_is_400():
    fake = FakeControlAdapter(error=FeedRejectedError("FreshRSS refused."))
    response = call(
        fake, "POST", "/api/v1/subscriptions", json={"feedUrl": "https://x.example.xml"}
    )

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "feed_rejected"


def test_create_subscription_missing_feed_url_is_422_without_upstream():
    fake = FakeControlAdapter()
    response = call(fake, "POST", "/api/v1/subscriptions", json={})

    assert response.status_code == 422
    assert fake.calls == []


def test_move_subscription_returns_204():
    fake = FakeControlAdapter()
    response = call(
        fake,
        "PATCH",
        f"/api/v1/subscriptions/{EXISTING_REF}",
        json={"categoryId": DEFAULT_CATEGORY},
    )

    assert response.status_code == 204
    assert fake.calls == [("move_category", "feed/7", DEFAULT_CATEGORY)]


def test_move_subscription_to_new_category_label_returns_204():
    """0013 Gate 3: newCategoryLabel = the explicit create-category path —
    the move itself creates the target category."""
    fake = FakeControlAdapter()
    response = call(
        fake,
        "PATCH",
        f"/api/v1/subscriptions/{EXISTING_REF}",
        json={"newCategoryLabel": "AI"},
    )

    assert response.status_code == 204
    assert fake.calls == [("move_to_new_category", "feed/7", "AI")]


def test_move_subscription_body_must_carry_exactly_one_target():
    """Empty body / both fields → 422 before any FreshRSS call."""
    fake = FakeControlAdapter()
    for body in [{}, {"categoryId": DEFAULT_CATEGORY, "newCategoryLabel": "AI"}]:
        response = call(
            fake, "PATCH", f"/api/v1/subscriptions/{EXISTING_REF}", json=body
        )
        assert response.status_code == 422
        assert fake.calls == []


def test_move_subscription_malformed_ref_is_400_without_upstream():
    fake = FakeControlAdapter()
    response = call(
        fake,
        "PATCH",
        "/api/v1/subscriptions/not-a-ref",
        json={"categoryId": DEFAULT_CATEGORY},
    )

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_subscription_reference"
    assert fake.calls == []


def test_move_subscription_not_found_is_404():
    fake = FakeControlAdapter(error=SubscriptionNotFound("No such subscription."))
    response = call(
        fake,
        "PATCH",
        f"/api/v1/subscriptions/{EXISTING_REF}",
        json={"categoryId": DEFAULT_CATEGORY},
    )

    assert response.status_code == 404
    assert response.json()["error"]["type"] == "subscription_not_found"


def test_delete_subscription_returns_204():
    fake = FakeControlAdapter()
    response = call(fake, "DELETE", f"/api/v1/subscriptions/{EXISTING_REF}")

    assert response.status_code == 204
    assert fake.calls == [("unsubscribe", "feed/7")]


def test_delete_subscription_malformed_ref_is_400():
    fake = FakeControlAdapter()
    response = call(fake, "DELETE", "/api/v1/subscriptions/e1.ZmVlZC83")

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_subscription_reference"
    assert fake.calls == []


def test_rename_category_route_returns_204():
    fake = FakeControlAdapter()
    response = call(
        fake,
        "PATCH",
        f"/api/v1/categories/{DEFAULT_CATEGORY}",
        json={"label": "Tech"},
    )

    assert response.status_code == 204
    assert fake.calls == [("rename_category", DEFAULT_CATEGORY, "Tech")]


def test_rename_category_conflict_is_409():
    fake = FakeControlAdapter(error=CategoryLabelConflict("Label taken."))
    response = call(
        fake,
        "PATCH",
        f"/api/v1/categories/{DEFAULT_CATEGORY}",
        json={"label": "Tech"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["type"] == "category_label_conflict"


def test_rename_default_category_immutable_is_409():
    fake = FakeControlAdapter(error=DefaultCategoryImmutable("Default category."))
    response = call(
        fake,
        "PATCH",
        f"/api/v1/categories/{DEFAULT_CATEGORY}",
        json={"label": "Tech"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["type"] == "default_category_immutable"


def test_control_routes_map_authentication_error():
    fake = FakeControlAdapter(error=AuthenticationError("FreshRSS rejected."))
    response = call(fake, "GET", "/api/v1/subscriptions")

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "authentication_error"


def test_read_feeds_route_still_works_alongside_control_routes():
    """The 0013 additions must not break the existing read path: the feeds
    route keeps using freshrss_adapter regardless of the control adapter."""
    from lumirss.adapters.freshrss import Feed

    class FakeReadAdapter:
        async def list_feeds(self):
            return [Feed(title="Existing Feed", feed_url="https://example.com/existing.xml")]

    fake_control = FakeControlAdapter()
    try:
        with TestClient(app) as client:
            app.state.freshrss_control_adapter = fake_control
            app.state.freshrss_adapter = FakeReadAdapter()
            feeds = client.get("/api/v1/feeds")
            subscriptions = client.get("/api/v1/subscriptions")

        assert feeds.status_code == 200
        assert feeds.json()[0]["title"] == "Existing Feed"
        assert subscriptions.status_code == 200
        assert fake_control.calls == [("list_subscriptions",)]
    finally:
        app.state.freshrss_control_adapter = None
        app.state.freshrss_adapter = None
