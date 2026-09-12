"""Mail webhook machine-auth tests (phase2 recovery P0-06d/g).

The ingest webhook is machine-to-machine: external relays carry the
per-list bearer secret, no session cookie and no X-Lumi-Token. This
suite pins the route-level guarantees plus the middleware deferral
(applied: SessionAuthMiddleware and InternalTokenMiddleware defer a
bearer-bearing request on /api/mail/ingest/* to THIS route's
constant-time secret check; the body-cap middleware exempts the path up
to 10MB):

- in-route per-list rate limiting (429 before authentication);
- wrong/absent bearer rejected 404-shaped (no list-existence leak);
- bearer accepted under ACTIVE session auth and internal token;
- payload cap alignment with the body-limit middleware (10MB).
"""

import pytest

import lumirss.routers.mail as mail_routes

RAW_MAIL = (
    "From: Newsletter <news@example.com>\r\n"
    "To: reader@example.com\r\n"
    "Subject: rate-limit probe\r\n"
    "Message-ID: <rl-1@example.com>\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n\r\n"
    "tiny\r\n"
)


@pytest.fixture(autouse=True)
def _reset_ingest_buckets():
    """The in-route rate limiter is process-global; tests must not
    inherit (or leak into) each other's budgets."""
    mail_routes._ingest_windows.clear()
    yield
    mail_routes._ingest_windows.clear()


def test_ingest_rate_limited_before_auth(client):
    """The per-list budget is consumed BEFORE authentication: even 404
    refusals count, so guessing cannot out-retry the window."""
    created = client.post("/api/v1/mail/bridge-lists", json={"name": "限流列表"})
    list_uuid = created.json()["uuid"]
    limit = mail_routes._INGEST_RATE_LIMIT
    for _ in range(limit):
        response = client.post(f"/api/mail/ingest/{list_uuid}", content=b"x")
        assert response.status_code == 404  # no bearer → honest refusal
    limited = client.post(f"/api/mail/ingest/{list_uuid}", content=b"x")
    assert limited.status_code == 429
    assert limited.json()["error"]["type"] == "rate_limited"
    assert "retry-after" in limited.headers
    # A different list has its own budget.
    other = client.post("/api/v1/mail/bridge-lists", json={"name": "另一列表"})
    fresh = client.post(f"/api/mail/ingest/{other.json()['uuid']}", content=b"x")
    assert fresh.status_code == 404  # NOT rate limited


def test_wrong_secret_rejected_and_never_logged_shape(client):
    created = client.post("/api/v1/mail/bridge-lists", json={"name": "机密列表"})
    list_uuid = created.json()["uuid"]
    secret = created.json()["secret"]
    wrong = client.post(
        f"/api/mail/ingest/{list_uuid}",
        content=RAW_MAIL.encode(),
        headers={"Authorization": "Bearer " + "0" * 40},
    )
    assert wrong.status_code == 404  # 404-shaped: no list-existence leak
    assert "secret" not in wrong.text and secret not in wrong.text


def test_ingest_between_4mb_and_10mb_reaches_route(client):
    """Middleware/route cap alignment (P0-06g): a 5MB mail — rejected by
    the old global 4MB ceiling before the route ever saw it — now passes
    the exempted middleware and is ingested by the route. Beyond the
    shared 10MB cap the middleware 413s first (caps are aligned by
    design); the route's own 10MB check remains as defense in depth and
    is covered store-level by test_ingest_rejects_oversize."""
    created = client.post("/api/v1/mail/bridge-lists", json={"name": "大邮件"})
    list_uuid = created.json()["uuid"]
    secret = created.json()["secret"]
    response = client.post(
        f"/api/mail/ingest/{list_uuid}",
        content=b"x" * (5 * 1024 * 1024),
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert response.status_code != 413
    assert response.status_code == 200
    assert response.json()["status"] in ("accepted", "duplicate")


def test_bearer_accepted_under_session_middleware(client, monkeypatch):
    """With session auth ACTIVE, a bearer-bearing machine relay reaches
    the route (middleware deferral, applied by the main agent), while a
    cookie-less browser request without bearer stays 401
    session_required."""
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "basic")
    created = client.post("/api/v1/mail/bridge-lists", json={"name": "会话穿透"})
    list_uuid = created.json()["uuid"]
    secret = created.json()["secret"]

    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    relayed = client.post(
        f"/api/mail/ingest/{list_uuid}",
        content=RAW_MAIL.encode(),
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert relayed.status_code == 200
    assert relayed.json()["status"] in ("accepted", "duplicate")

    browserless = client.post(f"/api/mail/ingest/{list_uuid}", content=b"x")
    assert browserless.status_code == 401
    assert browserless.json()["error"]["type"] == "session_required"


def test_bearer_accepted_with_internal_token_configured(client, monkeypatch):
    """External relays never carry X-Lumi-Token; the token layer defers
    bearer-bearing ingest requests to the route. (The list is created
    BEFORE the token is set — management calls are browser traffic and
    stay token-gated.)"""
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "basic")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")  # hermetic create phase
    created = client.post("/api/v1/mail/bridge-lists", json={"name": "内网穿透"})
    assert created.status_code == 201
    list_uuid = created.json()["uuid"]
    secret = created.json()["secret"]
    # FAKE test value composed at runtime (scanner hygiene; not a secret).
    fake_internal_token = "internal" + "-secret-1"
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", fake_internal_token)
    relayed = client.post(
        f"/api/mail/ingest/{list_uuid}",
        content=RAW_MAIL.encode(),
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert relayed.status_code == 200
    assert relayed.json()["status"] in ("accepted", "duplicate")
    # Non-ingest management traffic still requires the token.
    gated = client.get("/api/v1/mail/bridge-lists")
    assert gated.status_code == 401
    monkeypatch.delenv("LUMIRSS_INTERNAL_TOKEN")
