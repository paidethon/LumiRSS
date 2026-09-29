"""NEW-347 单项授权撤销中心 — 清单无令牌材料/逐项真实撤销/受影响
功能说明 + A/B 隔离。（零真实网络）"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册

AUTHZ_PATH = "/api/v1/privacy/authorizations"


def _enable_briefing(env, who):
    enabled = env["client"].post(
        "/api/v1/briefings/feed/enable", headers=env[who]
    )
    assert enabled.status_code == 200, enabled.text
    return enabled.json()["token"]


def _create_share_link(env, who):
    from lumirss.entryref import encode_entry_ref
    from new2xx_ab import seed_entry

    seed_entry(env, who, "n347-item", title="清单条目")
    created = env["client"].post(
        "/api/v1/privacy/share-links",
        json={
            "title": "授权中心链接",
            "scope": "titles",
            "entryRefs": [encode_entry_ref("n347-item")],
        },
        headers=env[who],
    )
    assert created.status_code == 201, created.text
    return created.json()


def _create_api_source(env):
    created = env["client"].post(
        "/api/v1/api-sources",
        json={
            "name": "发布源",
            "endpoint": "https://api.example.com/items",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "name"},
        },
        headers=env["a"],
    )
    assert created.status_code == 201, created.text
    return created.json()


def _create_webhook(env):
    created = env["client"].post(
        "/api/v1/webhooks/out-subscriptions",
        json={
            "eventType": "entry.starred",
            "targetUrl": "https://hook.example.com/n347",
        },
        headers=env["a"],
    )
    assert created.status_code == 201, created.text
    verified = env["client"].post(
        f"/api/v1/webhooks/out-subscriptions/{created.json()['id']}/verify",
        json={"token": created.json()["verifyToken"]},
        headers=env["a"],
    )
    assert verified.status_code == 200, verified.text
    return created.json()


def test_new347_inventory_lists_surfaces_without_token_material(ab_env):  # noqa: F811
    client = ab_env["client"]
    token = _enable_briefing(ab_env, "a")
    link = _create_share_link(ab_env, "a")
    source = _create_api_source(ab_env)
    webhook = _create_webhook(ab_env)

    inventory = client.get(AUTHZ_PATH, headers=ab_env["a"])
    assert inventory.status_code == 200, inventory.text
    payload = inventory.json()
    assert "令牌材料" in payload["note"]
    kinds = {item["kind"] for item in payload["items"]}
    assert {
        "briefing_feed",
        "share_link",
        "api_source",
        "out_webhook",
        "gpt_digest_feed",
    } <= kinds
    flat = str(payload).lower()
    assert token not in flat
    assert link["token"] not in flat
    briefing = next(
        item for item in payload["items"] if item["kind"] == "briefing_feed"
    )
    assert briefing["active"] is True
    assert briefing["affected"]  # 受影响功能说明存在

    # 隔离：B 的清单里没有 A 的链接/来源/订阅，凭据状态也互不可见。
    b_inventory = client.get(AUTHZ_PATH, headers=ab_env["b"]).json()
    b_refs = {(item["kind"], item["ref"]) for item in b_inventory["items"]}
    assert ("share_link", str(link["id"])) not in b_refs
    assert ("api_source", source["uuid"]) not in b_refs
    assert ("out_webhook", str(webhook["id"])) not in b_refs
    b_briefing = next(
        item for item in b_inventory["items"] if item["kind"] == "briefing_feed"
    )
    assert b_briefing["active"] is False


def test_new347_revoke_briefing_feed(ab_env):  # noqa: F811
    client = ab_env["client"]
    _enable_briefing(ab_env, "a")
    revoked = client.post(
        f"{AUTHZ_PATH}/briefing_feed/default/revoke", headers=ab_env["a"]
    )
    assert revoked.status_code == 200, revoked.text
    assert "立即失效" in revoked.json()["affected"]

    state = client.get("/api/v1/briefings/feed", headers=ab_env["a"]).json()
    assert state["enabled"] is False

    again = client.post(
        f"{AUTHZ_PATH}/briefing_feed/default/revoke", headers=ab_env["a"]
    )
    assert again.status_code == 404

    events = client.get(f"{AUTHZ_PATH}/events", headers=ab_env["a"]).json()["items"]
    assert any(
        event["kind"] == "briefing_feed" and event["ref"] == "default"
        for event in events
    )


def test_new347_revoke_share_link_and_isolation(ab_env):  # noqa: F811
    client = ab_env["client"]
    link = _create_share_link(ab_env, "a")
    # B 撤 A 的链接 → 404。
    forbidden = client.post(
        f"{AUTHZ_PATH}/share_link/{link['id']}/revoke", headers=ab_env["b"]
    )
    assert forbidden.status_code == 404
    revoked = client.post(
        f"{AUTHZ_PATH}/share_link/{link['id']}/revoke", headers=ab_env["a"]
    )
    assert revoked.status_code == 200
    assert client.get(f"/shares/{link['token']}").status_code == 404


def test_new347_unknown_kind_404(ab_env):  # noqa: F811
    client = ab_env["client"]
    response = client.post(
        f"{AUTHZ_PATH}/unknown_kind/x/revoke", headers=ab_env["a"]
    )
    assert response.status_code == 404
