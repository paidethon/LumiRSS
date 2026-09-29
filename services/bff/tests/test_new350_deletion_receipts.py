"""NEW-350 个人数据删除范围预览与处理回执 — 预览真实计数/确认实际
处理/回执为已发生事实/FreshRSS 边界 + A/B 隔离。"""

from new2xx_ab import PASSWORD, ab_env, seed_entry  # noqa: F401 — pytest 夹具注册

PREVIEW_PATH = "/api/v1/me/deletion/preview"
CONFIRM_PATH = "/api/v1/me/deletion/confirm"
RECEIPTS_PATH = "/api/v1/me/deletion/receipts"


def _setup_a_shared_copies(env):
    """A：种子条目 + 启用简报 feed + 建一条共享链接。"""
    client = env["client"]
    seed_entry(env, "a", "n350-item", title="删除预览条目", content_text="x" * 50)
    enabled = client.post("/api/v1/briefings/feed/enable", headers=env["a"])
    assert enabled.status_code == 200
    from lumirss.entryref import encode_entry_ref

    created = client.post(
        "/api/v1/me/share-links",
        json={
            "title": "将被撤销",
            "scope": "titles",
            "entryRefs": [encode_entry_ref("n350-item")],
        },
        headers=env["a"],
    )
    assert created.status_code == 201
    return created.json()["token"]


def test_new350_preview_counts_and_shared_rules(ab_env):  # noqa: F811
    client = ab_env["client"]
    _setup_a_shared_copies(ab_env)
    preview = client.get(PREVIEW_PATH, headers=ab_env["a"])
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["categories"]["entries"] >= 1
    assert payload["categories"]["aiTaskLogs"] == 0
    copies = payload["sharedCopies"]
    rules = {rule["copy"]: rule for rule in copies}
    assert any("共享链接" in key and "1 条" in key for key in rules)
    freshrss = next(rule for rule in copies if "FreshRSS" in rule["copy"])
    assert freshrss["action"] == "none"
    assert "不在 Lumi 删除范围内" in freshrss["rule"]

    # 隔离：B 的预览计数是 B 自己的（entries=0）。
    b_preview = client.get(PREVIEW_PATH, headers=ab_env["b"]).json()
    assert b_preview["categories"]["entries"] == 0


def test_new350_confirm_validation(ab_env):  # noqa: F811
    client = ab_env["client"]
    bad_text = client.post(
        CONFIRM_PATH,
        json={"password": "x", "confirmText": "delete"},
        headers=ab_env["a"],
    )
    assert bad_text.status_code == 422
    owner_denied = client.post(
        CONFIRM_PATH,
        json={"password": "x", "confirmText": "DELETE"},
        headers=ab_env["owner"],
    )
    assert owner_denied.status_code == 403
    assert owner_denied.json()["error"]["type"] == "owner_undeactivatable"


def test_new350_confirm_processes_and_receipt(ab_env):  # noqa: F811
    """确认 → 逐类实际处理 + 回执；旧会话被吊销；重新登录后回执
    可查、停用标记在；共享链接立即失效。"""
    client = ab_env["client"]
    share_token = _setup_a_shared_copies(ab_env)
    assert client.get(f"/shares/{share_token}").status_code == 200

    wrong_password = client.post(
        CONFIRM_PATH,
        json={"password": "totally-wrong", "confirmText": "DELETE"},
        headers=ab_env["a"],
    )
    assert wrong_password.status_code == 401

    confirmed = client.post(
        CONFIRM_PATH,
        json={
            "password": PASSWORD,
            "confirmText": "DELETE",
        },
        headers=ab_env["a"],
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    receipt = body["receipt"]
    actions = {(a["category"], a["action"]): a["count"] for a in receipt["actions"]}
    assert actions[("briefing_feed", "revoke")] == 1
    assert actions[("share_links", "revoke")] == 1
    assert actions[("search_snapshots", "purge")] >= 0
    assert receipt["scheduledDeletionAt"] > receipt["requestedAt"]
    assert any("FreshRSS" in note for note in receipt["retained"])
    assert any("没有自动作业" in note for note in receipt["retained"])

    # 共享链接立即失效；旧会话被吊销（旧 cookie 401）。
    assert client.get(f"/shares/{share_token}").status_code == 404
    assert (
        client.get("/api/v1/me/access-log", headers=ab_env["a"]).status_code == 401
    )

    # 停用后连登录都被如实拦下（403 account_deactivated 携带宽限期
    # 状态）——回执本体已在确认响应里；持久化经模块层（真实库）验证。
    import asyncio

    from lumirss.new350_deletion_receipts import list_receipts
    from lumirss.user_scope import user_context

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": PASSWORD},
    )
    assert login.status_code == 403
    assert login.json()["error"]["type"] == "account_deactivated"
    assert "scheduledDeletionAt" in login.json()["error"]

    async def read_receipts():
        with user_context(ab_env["a"]["userId"]):
            return await list_receipts(ab_env["app"].state.db, 10)

    stored = asyncio.run(read_receipts())
    assert len(stored) == 1 and stored[0]["id"] == receipt["id"]
    assert stored[0]["actions"][0]["category"] == "briefing_feed"


def test_new350_isolation_b_untouched(ab_env):  # noqa: F811
    """A 确认删除不动 B 的任何共享面（B 的简报 feed 仍然有效）。"""
    client = ab_env["client"]
    _setup_a_shared_copies(ab_env)
    _b_token = client.post(
        "/api/v1/briefings/feed/enable", headers=ab_env["b"]
    ).json()["token"]
    confirmed = client.post(
        CONFIRM_PATH,
        json={
            "password": PASSWORD,
            "confirmText": "DELETE",
        },
        headers=ab_env["a"],
    )
    assert confirmed.status_code == 200
    assert client.get(f"/feeds/briefings/{_b_token}.atom").status_code == 200
    b_preview = client.get(PREVIEW_PATH, headers=ab_env["b"]).json()
    assert b_preview["categories"]["entries"] == 0
