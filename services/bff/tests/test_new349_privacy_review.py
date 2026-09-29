"""NEW-349 隐私检查向导 — 逐项清单/逐项真实撤回/无一键全删（404）/
不可撤回项如实说明 + A/B 隔离。（零真实网络）"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册

REVIEW_PATH = "/api/v1/privacy/review"


def _enable_briefing(env, who):
    enabled = env["client"].post(
        "/api/v1/briefings/feed/enable", headers=env[who]
    )
    assert enabled.status_code == 200, enabled.text


def test_new349_review_items_categorized(ab_env):  # noqa: F811
    client = ab_env["client"]
    response = client.get(REVIEW_PATH, headers=ab_env["a"])
    assert response.status_code == 200, response.text
    payload = response.json()
    categories = {item["category"] for item in payload["items"]}
    assert {"sharing", "external_ai", "device_cache", "server_records"} <= categories
    assert "每项撤回独立确认" in payload["note"]
    offline = next(
        item for item in payload["items"] if item["key"] == "reader_offline_cache"
    )
    assert offline["withdraw"]["available"] is False
    assert "服务端" in offline["withdraw"]["how"]


def test_new349_withdraw_briefing_feed(ab_env):  # noqa: F811
    client = ab_env["client"]
    _enable_briefing(ab_env, "a")
    withdrawn = client.post(
        f"{REVIEW_PATH}/briefing_feed/withdraw", json={}, headers=ab_env["a"]
    )
    assert withdrawn.status_code == 200, withdrawn.text
    state = client.get("/api/v1/briefings/feed", headers=ab_env["a"]).json()
    assert state["enabled"] is False
    review = client.get(REVIEW_PATH, headers=ab_env["a"]).json()
    assert any(
        action["key"] == "briefing_feed" for action in review["recentActions"]
    )
    again = client.post(
        f"{REVIEW_PATH}/briefing_feed/withdraw", json={}, headers=ab_env["a"]
    )
    assert again.status_code == 404


def test_new349_no_bulk_withdraw(ab_env):  # noqa: F811
    """硬规则：一键全删不存在——批量端点 404，响应里也没有批量动作。"""
    client = ab_env["client"]
    bulk = client.post(f"{REVIEW_PATH}/withdraw-all", json={}, headers=ab_env["a"])
    assert bulk.status_code == 404
    payload = client.get(REVIEW_PATH, headers=ab_env["a"]).json()
    for item in payload["items"]:
        assert item["withdraw"]["actionKey"] != "withdraw_all"


def test_new349_withdraw_share_link_with_ref(ab_env):  # noqa: F811
    client = ab_env["client"]
    from lumirss.entryref import encode_entry_ref
    from new2xx_ab import seed_entry

    seed_entry(ab_env, "a", "n349-item", title="向导条目")
    created = client.post(
        "/api/v1/privacy/share-links",
        json={
            "title": "向导链接",
            "scope": "titles",
            "entryRefs": [encode_entry_ref("n349-item")],
        },
        headers=ab_env["a"],
    )
    link_id = created.json()["id"]
    missing_ref = client.post(
        f"{REVIEW_PATH}/share_link/withdraw", json={}, headers=ab_env["a"]
    )
    assert missing_ref.status_code == 404
    withdrawn = client.post(
        f"{REVIEW_PATH}/share_link/withdraw",
        json={"ref": str(link_id)},
        headers=ab_env["a"],
    )
    assert withdrawn.status_code == 200
    # 隔离：B 的向导从来看不到 A 的链接（撤完更是无对象可撤）。
    b_review = client.get(REVIEW_PATH, headers=ab_env["b"]).json()
    assert all("向导链接" not in item["detail"] for item in b_review["items"])


def test_new349_unknown_item_and_unavailable(ab_env):  # noqa: F811
    client = ab_env["client"]
    unknown = client.post(
        f"{REVIEW_PATH}/not_an_item/withdraw", json={}, headers=ab_env["a"]
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["type"] == "unknown_review_item"
    # device_cache 类项不可撤回（服务端触达不到）→ 404。
    offline = client.post(
        f"{REVIEW_PATH}/reader_offline_cache/withdraw", json={}, headers=ab_env["a"]
    )
    assert offline.status_code == 404
