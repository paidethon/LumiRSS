"""NEW-342 第三方请求清单 — 配置推导/诚实注记/可选请求真实开关 +
A/B 隔离。（零网络调用）"""


from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册

INVENTORY_PATH = "/api/v1/privacy/third-party-requests"


def test_new342_inventory_shape_and_honesty(ab_env):  # noqa: F811
    """清单按 reading/ai 两个作用域分组；注记说明这是配置推导而非
    请求日志；条目都带 optional/optoutKey 元数据。"""
    client = ab_env["client"]
    response = client.get(INVENTORY_PATH, headers=ab_env["a"])
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "不是逐请求网络日志" in payload["note"]
    keys_reading = {item["key"] for item in payload["reading"]}
    assert {"freshrss", "rsshub", "remote_images", "outbound_webhooks"} <= keys_reading
    keys_ai = {item["key"] for item in payload["ai"]}
    assert {"ai-provider", "tts"} <= keys_ai
    for item in [*payload["reading"], *payload["ai"]]:
        assert isinstance(item["optional"], bool)
        assert "purpose" in item
    # host 只含主机名或为空：绝无密钥/完整 URL（带路径）。
    for item in [*payload["reading"], *payload["ai"]]:
        if item["host"]:
            assert "://" not in item["host"]


def test_new342_remote_images_toggle_is_real_and_per_user(ab_env):  # noqa: F811
    """关掉 remote_images 真实写入便携设置 readerImageMode=hidden；
    B 的清单不受 A 的开关影响（per-user）。"""
    client = ab_env["client"]
    before_b = client.get(INVENTORY_PATH, headers=ab_env["b"]).json()
    remote_b = next(i for i in before_b["reading"] if i["key"] == "remote_images")
    assert remote_b["disabled"] is False

    toggled = client.post(
        f"{INVENTORY_PATH}/remote_images/toggle",
        json={"disabled": True},
        headers=ab_env["a"],
    )
    assert toggled.status_code == 200, toggled.text
    assert toggled.json()["disabled"] is True

    after_a = client.get(INVENTORY_PATH, headers=ab_env["a"]).json()
    remote_a = next(i for i in after_a["reading"] if i["key"] == "remote_images")
    assert remote_a["disabled"] is True
    assert any(
        action["key"] == "remote_images" and action["action"] == "off"
        for action in after_a["recentActions"]
    )

    after_b = client.get(INVENTORY_PATH, headers=ab_env["b"]).json()
    remote_b2 = next(i for i in after_b["reading"] if i["key"] == "remote_images")
    assert remote_b2["disabled"] is False

    # 恢复：再开一次 → off 被覆盖为 on。
    restore = client.post(
        f"{INVENTORY_PATH}/remote_images/toggle",
        json={"disabled": False},
        headers=ab_env["a"],
    )
    assert restore.status_code == 200
    final_a = client.get(INVENTORY_PATH, headers=ab_env["a"]).json()
    remote_a2 = next(i for i in final_a["reading"] if i["key"] == "remote_images")
    assert remote_a2["disabled"] is False


def test_new342_webhooks_toggle_pauses_real_subscriptions(ab_env):  # noqa: F811
    """外发订阅开关：暂停/恢复落在订阅状态上（真实停发语义）。"""
    client = ab_env["client"]
    created = client.post(
        "/api/v1/webhooks/out-subscriptions",
        json={"eventType": "entry.starred", "targetUrl": "https://hook.example.com/n342"},
        headers=ab_env["a"],
    )
    assert created.status_code == 201, created.text
    subscription_id = created.json()["id"]
    verified = client.post(
        f"/api/v1/webhooks/out-subscriptions/{subscription_id}/verify",
        json={"token": created.json()["verifyToken"]},
        headers=ab_env["a"],
    )
    assert verified.status_code == 200, verified.text

    off = client.post(
        f"{INVENTORY_PATH}/outbound_webhooks/toggle",
        json={"disabled": True},
        headers=ab_env["a"],
    )
    assert off.status_code == 200, off.text
    assert "暂停" in off.json()["detail"]
    subs = client.get(
        "/api/v1/webhooks/out-subscriptions", headers=ab_env["a"]
    ).json()["items"]
    assert all(item["state"] == "paused" for item in subs)

    on = client.post(
        f"{INVENTORY_PATH}/outbound_webhooks/toggle",
        json={"disabled": False},
        headers=ab_env["a"],
    )
    assert on.status_code == 200
    subs2 = client.get(
        "/api/v1/webhooks/out-subscriptions", headers=ab_env["a"]
    ).json()["items"]
    assert all(item["state"] == "active" for item in subs2)

    # B 的订阅面不受影响（A 开关触不到 B 的订阅——这里 B 无订阅）。
    inv_b = client.get(INVENTORY_PATH, headers=ab_env["b"]).json()
    hook_b = next(i for i in inv_b["reading"] if i["key"] == "outbound_webhooks")
    assert hook_b["host"] is None


def test_new342_unknown_toggle_404(ab_env):  # noqa: F811
    client = ab_env["client"]
    response = client.post(
        f"{INVENTORY_PATH}/freshrss/toggle",
        json={"disabled": True},
        headers=ab_env["a"],
    )
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "unknown_toggle"


def test_new342_inventory_pure_function():
    """纯函数组装：未配置项 host=None 且 disabled 只由 optouts 决定。"""
    from lumirss.new342_third_party_requests import build_third_party_inventory

    payload = build_third_party_inventory(
        freshrss_host=None,
        rsshub_host="rsshub.example",
        ai_host="api.ai.example",
        libretranslate_host=None,
        tts_host=None,
        webdav_host=None,
        imap_host=None,
        remote_images_hidden=True,
        webhook_hosts=["hook.example"],
        share_link_count=2,
        optouts={"remote_images": True},
    )
    freshrss = next(i for i in payload["reading"] if i["key"] == "freshrss")
    assert freshrss["host"] is None and freshrss["optional"] is False
    remote = next(i for i in payload["reading"] if i["key"] == "remote_images")
    assert remote["disabled"] is True
    hooks = next(i for i in payload["reading"] if i["key"] == "outbound_webhooks")
    assert hooks["host"] == "hook.example"
