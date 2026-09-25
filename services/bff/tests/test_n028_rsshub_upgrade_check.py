"""N028 路由升级兼容检查 — POST/GET /admin/rsshub/upgrade-check。

覆盖：
- 报告行写入：路由键采集（订阅反推 + 收藏）、逐路由 ok/failed 状态、
  entryCount、failureClass、checkedImage 锚定目录快照固定镜像；
- targetImage 语义：缺席 → targetStatus None；声明 → 恒 'pending'
  （检查只对当前运行实例探测，绝不臆造「新镜像已生效」）；
- 有界：超出 MAX_CHECK_ROUTES 的路由如实 skipped（check_budget_exceeded）；
- 敏感哨兵路由（收藏里 token=***）→ skipped，绝无重放真实值；
- keep-last-3；
- member 403（session 模式夹具）。

探测用 app.state.rsshub_route_probe 注入（N026 同一缝），无真实网络。
"""

import asyncio
import json
import secrets as _secrets
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lumirss.feed_preview import FeedPreview
from lumirss.main import app
from lumirss.rsshub import RssHubFetchError, RssHubPreviewCache
from lumirss.rsshub_upgrade_check import pinned_image
from lumirss.storage import Database
from lumirss.subscriptionref import encode_subscription_ref


@pytest.fixture()
def check_client(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    from lumirss.routers import rsshub as rsshub_router

    with TestClient(app) as test_client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        app.state.rsshub_preview_cache = RssHubPreviewCache(ttl_s=0.0)

        class _FakeControl:
            async def list_subscriptions(self):
                return [
                    SimpleNamespace(
                        stream_id="feed/1",
                        subscription_ref=encode_subscription_ref("feed/1"),
                        title="HN",
                        feed_url="http://rsshub.test:1200/hackernews",
                    )
                ]

        app.state.freshrss_control_adapter = _FakeControl()
        rsshub_router._refresh_buckets.clear()
        yield test_client
    app.state.rsshub_route_probe = None
    app.state.freshrss_control_adapter = None


def _install_probe(routes: dict[str, object]) -> None:
    """routes: routeId -> FeedPreview | Exception（按模板 id 简单路由）。"""

    async def probe(route_id, params, *, base_override=None):
        outcome = routes.get(route_id, _preview(route_id))
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, FeedPreview)
        return outcome

    app.state.rsshub_route_probe = probe


def _preview(route_id: str, entry_count: int = 3) -> FeedPreview:
    return FeedPreview(
        title=route_id,
        feed_url="http://rsshub.test:1200/x",
        site_url=None,
        description=None,
        format="rss",
        already_subscribed=False,
        entry_count=entry_count,
    )


def _favorite(client, route_id, params, label=""):
    response = client.put(
        "/api/v1/rsshub/routes/favorites",
        json={"routeId": route_id, "params": params, "label": label},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _run_check(client, **body):
    return client.post("/api/v1/admin/rsshub/upgrade-check", json=body)


def test_report_rows_written_with_statuses(check_client):
    _install_probe(
        {
            "hackernews": _preview("hackernews", 7),
            "cnbeta": RssHubFetchError(
                "RSSHub answered HTTP 500.", failure_class="upstream_reject"
            ),
        }
    )
    _favorite(check_client, "hackernews", {})
    _favorite(check_client, "cnbeta", {})

    response = _run_check(check_client, targetImage="diygod/rsshub:next")
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["routeCount"] == 2
    assert report["okCount"] == 1
    assert report["failedCount"] == 1
    assert report["skippedCount"] == 0
    by_key = {route["routeKey"]: route for route in report["routes"]}
    assert by_key["hackernews"]["status"] == "ok"
    assert by_key["hackernews"]["entryCount"] == 7
    assert by_key["hackernews"]["origin"] == "subscription"
    assert by_key["cnbeta"]["status"] == "failed"
    assert by_key["cnbeta"]["failureClass"] == "upstream_reject"
    # checkedImage = 目录快照固定镜像；targetImage 恒 pending
    assert report["checkedImage"] == pinned_image()
    assert report["targetImage"] == "diygod/rsshub:next"
    assert report["targetStatus"] == "pending"
    assert report["ranAt"]

    listing = check_client.get("/api/v1/admin/rsshub/upgrade-check").json()
    assert [item["id"] for item in listing["items"]] == [report["id"]]


def test_target_image_absent_is_honestly_none(check_client):
    _install_probe({"hackernews": _preview("hackernews")})
    _favorite(check_client, "hackernews", {})
    report = _run_check(check_client).json()
    assert report["targetImage"] is None
    assert report["targetStatus"] is None


def test_check_is_bounded_with_skipped_overflow(check_client):
    _install_probe({"hackernews": _preview("hackernews")})
    for index in range(15):
        _favorite(
            check_client,
            "github-starred-repos",
            {"user": f"user{index:02d}"},
        )
    report = _run_check(check_client).json()
    # 15 条收藏 + 夹具订阅（hackernews）= 16 个去重后的路由键
    assert report["routeCount"] == 16
    probed = [r for r in report["routes"] if r["status"] != "skipped"]
    skipped = [r for r in report["routes"] if r["status"] == "skipped"]
    assert len(probed) == 12
    assert len(skipped) == 4
    assert all(
        route["failureClass"] == "check_budget_exceeded" for route in skipped
    )


def test_sensitive_sentinel_route_skipped_never_probed(check_client):
    probed_ids: list[str] = []

    async def probe(route_id, params, *, base_override=None):
        probed_ids.append(route_id)
        return _preview(route_id)

    app.state.rsshub_route_probe = probe
    _favorite(check_client, "github-starred-repos", {"user": "DIYgod", "apiKey": "s3cret"})
    report = _run_check(check_client).json()
    by_key = {route["routeKey"]: route for route in report["routes"]}
    sensitive_key = "github-starred-repos|apiKey=***&user=DIYgod"
    assert by_key[sensitive_key]["status"] == "skipped"
    assert by_key[sensitive_key]["failureClass"] == "sensitive_params_unavailable"
    # 敏感路由绝不进入探测（夹具订阅 hackernews 是唯一被探测者）
    assert "github-starred-repos" not in probed_ids
    assert probed_ids == ["hackernews"]


def test_keep_last_three_reports(check_client):
    _install_probe({"hackernews": _preview("hackernews")})
    _favorite(check_client, "hackernews", {})
    for _ in range(4):
        assert _run_check(check_client).status_code == 200
    listing = check_client.get("/api/v1/admin/rsshub/upgrade-check").json()
    ids = [item["id"] for item in listing["items"]]
    assert len(ids) == 3
    assert ids == sorted(ids, reverse=True)  # 新→旧


def test_pinned_image_comes_from_generated_snapshot():
    snapshot = json.loads(
        (Path(__file__).resolve().parents[1] / "src/lumirss/rsshub_routes.generated.json")
        .read_text(encoding="utf-8")
    )
    assert pinned_image() == snapshot["_meta"]["rsshubImage"]


def test_probe_one_malformed_key_is_skipped():
    from lumirss.routers.rsshub import _catalog_route
    from lumirss.rsshub_upgrade_check import _probe_one

    class _Request:
        class state:  # noqa: N801 — 简单命名空间
            db = None

    result = asyncio.run(_probe_one(_Request(), "hackernews|&bad", "favorite"))
    assert result["status"] == "skipped"
    assert result["failureClass"] == "malformed_route_key"
    assert _catalog_route("hackernews") is not None


def _session_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()


PASSWORD = "uc-" + _secrets.token_urlsafe(9)


def test_member_403_on_upgrade_check(monkeypatch, tmp_path):
    _session_env(monkeypatch, tmp_path)
    from lumirss.accounts_store import AccountsStore, hash_password

    with TestClient(app, base_url="http://lumirss.test") as client:
        async def _set_owner_password():
            database = Database(tmp_path / "lumi.sqlite")
            await database.migrate()
            for row in await AccountsStore(database).list_users(limit=50):
                if row["role"] == "owner":
                    await AccountsStore(database).set_password_hash(
                        str(row["id"]), hash_password(PASSWORD)
                    )
                    return

        asyncio.run(_set_owner_password())
        owner_login = client.post(
            "/api/v1/auth/login", json={"username": "owner", "password": PASSWORD}
        )
        assert owner_login.status_code == 200, owner_login.text
        owner_headers = {"cookie": owner_login.headers["set-cookie"].split(";")[0]}
        invite = client.post(
            "/api/v1/admin/invites", json={"label": "alice"}, headers=owner_headers
        )
        activation = client.post(
            "/api/v1/auth/activate",
            json={"token": invite.json()["token"], "username": "alice", "password": PASSWORD},
        )
        assert activation.status_code == 200, activation.text
        alice = {"cookie": activation.headers["set-cookie"].split(";")[0]}

        member_post = client.post(
            "/api/v1/admin/rsshub/upgrade-check", json={}, headers=alice
        )
        member_get = client.get(
            "/api/v1/admin/rsshub/upgrade-check", headers=alice
        )
    assert member_post.status_code == 403
    assert member_post.json()["error"]["type"] == "forbidden"
    assert member_get.status_code == 403
