"""NEW-207 RSSHub 参数表单 —— schema/离线校验/验证后添加/脱敏台账。

验收问题对照：
- 谁/输入：用户选路由 → 按明确参数定义填表（required/pattern/example/
  help 全部来自 Lumi 自有目录）；
- 入口：GET /api/v1/new207/rsshub-form/{routeId}（表单 schema）→
  validate（离线逐参数校验）→（样本预览走既有 rsshub/preview）→
  apply（验证后添加）；
- 之前/之后：填错（缺必填/格式不符/未知键）→ 422 rsshub_form_invalid
  逐参数 errors，**不产生任何订阅**；填对 + confirmed → 服务端拼装
  订阅地址（浏览器永不接触 RSSHUB base 配置）→ 订阅成功 + 脱敏台账；
- 不要求手拼 URL：generatedPath 由服务端 build_path 产出；
- 失败/恢复：未确认 422；已订 409 already_subscribed（预先检查 +
  上游冲突都归并）；base 未配置 422 rsshub_not_configured；
- A/B 隔离：B 的台账 A 不可见。

上游交互走 SimpleNamespace 假件；RSSHUB_BASE_URL 用 monkeypatch 注入。
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lumirss.new207_rsshub_form import RssHubFormStore, validate_form
from lumirss.routers import new207_rsshub_form as form_router
from lumirss.rsshub import CATALOG
from lumirss.subscriptionref import encode_subscription_ref
from new201_210_harness import feature_app

ROUTE = "github-starred-repos"  # 参数 user：required, pattern ^[a-zA-Z0-9-]{1,39}$
ROUTE_NO_PARAMS = "hackernews"


@pytest.fixture()
def make_client(tmp_path, monkeypatch):
    clients = []
    monkeypatch.setenv("RSSHUB_BASE_URL", "https://rsshub.example")

    def _make(*routers, adapter=None):
        app = feature_app(tmp_path, *routers)
        if adapter is not None:
            app.state.freshrss_control_adapter = adapter
        client = TestClient(app)
        clients.append(client)
        return client, app

    yield _make
    for client in clients:
        client.close()


def _adapter(subs, calls):
    async def _list():
        return list(subs)

    async def _subscribe(feed_url, category_id=None, title=None):
        calls.append(("subscribe", feed_url, title))
        created = SimpleNamespace(
            stream_id="feed/77",
            subscription_ref=encode_subscription_ref("feed/77"),
            title=title or "",
            feed_url=feed_url,
            category_id=None,
            category_label=None,
        )
        subs.append(created)
        return created

    return SimpleNamespace(list_subscriptions=_list, subscribe=_subscribe)


def test_new207_validate_pure():
    route = next(r for r in CATALOG if r.id == ROUTE)
    ok = validate_form(route, {"user": "DIYgod"})
    assert ok["valid"] is True
    assert ok["generatedPath"] == "/github/starred_repos/DIYgod"

    bad = validate_form(route, {"user": "有 空 格"})
    assert bad["valid"] is False
    assert bad["errors"][0]["code"] == "pattern_mismatch"
    missing = validate_form(route, {})
    assert missing["errors"][0]["code"] == "missing_required"
    unknown = validate_form(route, {"token": "x"})
    assert unknown["errors"][0]["code"] == "unknown"

    no_param = next(r for r in CATALOG if r.id == ROUTE_NO_PARAMS)
    assert validate_form(no_param, {})["generatedPath"] == "/hackernews"
    mixed = validate_form(route, {"user": "ok", "extra": "x"})
    assert mixed["valid"] is False
    assert [e["code"] for e in mixed["errors"]] == ["unknown"], "未知键走 errors 不抛异常"


def test_new207_schema_validate_apply_flow(make_client):
    calls: list = []
    subs: list = []
    client, _app = make_client(form_router.router, adapter=_adapter(subs, calls))

    schema = client.get(f"/api/v1/new207/rsshub-form/{ROUTE}")
    assert schema.status_code == 200
    body = schema.json()
    assert body["pathTemplate"] == "/github/starred_repos/{user}"
    assert body["parameters"][0]["required"] is True

    # 填错：validate 离线报错；apply 拒绝（不产生订阅）
    invalid = client.post(
        f"/api/v1/new207/rsshub-form/{ROUTE}/validate", json={"params": {}}
    )
    assert invalid.status_code == 200
    assert invalid.json()["valid"] is False
    apply_invalid = client.post(
        f"/api/v1/new207/rsshub-form/{ROUTE}/apply",
        json={"params": {}, "confirmed": True},
    )
    assert apply_invalid.status_code == 422
    assert apply_invalid.json()["error"]["type"] == "rsshub_form_invalid"
    assert calls == [], "校验未过绝不订阅"

    # 未确认 → 422
    unconfirmed = client.post(
        f"/api/v1/new207/rsshub-form/{ROUTE}/apply",
        json={"params": {"user": "DIYgod"}},
    )
    assert unconfirmed.status_code == 422
    assert unconfirmed.json()["error"]["type"] == "confirmation_required"

    # 未知路由 → 404
    assert client.get("/api/v1/new207/rsshub-form/nope").status_code == 404

    # 填对 + 确认 → 订阅成功（服务端拼 URL），台账脱敏
    applied = client.post(
        f"/api/v1/new207/rsshub-form/{ROUTE}/apply",
        json={"params": {"user": "DIYgod"}, "title": "DIYgod 的星标", "confirmed": True},
    )
    assert applied.status_code == 201, applied.text
    result = applied.json()
    assert result["subscription"]["feedUrl"] == "https://rsshub.example/github/starred_repos/DIYgod"
    assert ("subscribe", result["subscription"]["feedUrl"], "DIYgod 的星标") in calls

    # 已订同地址 → 409 already_subscribed（预先检查，零二次订阅）
    duplicate = client.post(
        f"/api/v1/new207/rsshub-form/{ROUTE}/apply",
        json={"params": {"user": "DIYgod"}, "confirmed": True},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["type"] == "already_subscribed"

    # 台账脱敏：params 只存 '***' 形态（若含敏感键）；此处无敏感键 → 原样
    uses = client.get(f"/api/v1/new207/rsshub-form/{ROUTE}/uses").json()["items"]
    assert uses and uses[0]["params"] == {"user": "DIYgod"}


def test_new207_sensitive_param_masked_in_ledger(tmp_path, monkeypatch):
    """敏感参数键值只以 '***' 落台账（N021 同一 mask_params 规则）。"""
    import asyncio
    import json as _json
    import sqlite3

    from lumirss.storage import Database
    from lumirss.user_scope import RoutingDatabase, user_context

    Database(tmp_path / "control.sqlite")  # 控制库先行（harness 同款）
    async def _run():
        with user_context("fred"):
            store = RssHubFormStore(RoutingDatabase(tmp_path / "control.sqlite", tmp_path / "users"))
            await store.record(
                route_id=ROUTE,
                params={"user": "DIYgod", "token": "hunter2"},
                feed_url="https://rsshub.example/github/starred_repos/DIYgod",
            )
            uses = await store.list_uses()
            assert uses[0]["params"]["token"] == "***"
            assert uses[0]["params"]["user"] == "DIYgod"

    asyncio.run(_run())

    conn = sqlite3.connect(str(tmp_path / "users" / "fred" / "lumi.sqlite"))
    raw = conn.execute(
        "SELECT params_json FROM new207_rsshub_form_uses LIMIT 1"
    ).fetchone()[0]
    conn.close()
    assert "hunter2" not in raw
    assert _json.loads(raw)["token"] == "***"


def test_new207_per_user_isolation(make_client):
    calls: list = []
    subs: list = []
    client, _app = make_client(form_router.router, adapter=_adapter(subs, calls))
    bob = {"x-test-user": "bob"}
    applied = client.post(
        f"/api/v1/new207/rsshub-form/{ROUTE_NO_PARAMS}/apply",
        json={"params": {}, "confirmed": True},
        headers=bob,
    )
    assert applied.status_code == 201
    assert client.get(f"/api/v1/new207/rsshub-form/{ROUTE_NO_PARAMS}/uses").json()["items"] == []
    mine = client.get(
        f"/api/v1/new207/rsshub-form/{ROUTE_NO_PARAMS}/uses", headers=bob
    ).json()["items"]
    assert len(mine) == 1
