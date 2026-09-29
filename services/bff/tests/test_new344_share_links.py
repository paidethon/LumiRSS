"""NEW-344 共享链接使用范围 — 三档范围渲染（所见即所发）/预览一致性/
full 需设备信任（NEW-346 消费点）/撤销与 A/B 隔离。（零真实网络）"""


from new2xx_ab import ab_env, seed_entry  # noqa: F401 — pytest 夹具注册

LINKS_PATH = "/api/v1/privacy/share-links"
def _seed_two_entries(env) -> list[str]:
    from lumirss.entryref import encode_entry_ref

    seed_entry(
        env,
        "a",
        "n344-item-1",
        title="公开安全公告",
        content_text="这是可以完整公开的第一段正文，" * 30,
    )
    seed_entry(
        env,
        "a",
        "n344-item-2",
        title="第二篇：目录条目",
        content_text="第二篇正文内容，用于验证范围裁剪。" * 20,
    )
    return [encode_entry_ref("n344-item-1"), encode_entry_ref("n344-item-2")]


async def _allow_password() -> bool:
    return True


def _grant_trust(env, headers, *, hours=12):
    """直接经模块授予（路由层另有密码复核单测覆盖）。"""
    from lumirss.auth_store import device_fingerprint, device_label_from_ua
    from lumirss.new346_device_trust import grant_trust

    async def run():
        from lumirss.user_scope import user_context

        with user_context(env["a"]["userId"]):
            return await grant_trust(
                env["app"].state.db,
                fingerprint=device_fingerprint("testclient"),
                device_label=device_label_from_ua("testclient"),
                verify_password=_allow_password,
                hours=hours,
            )

    import asyncio

    return asyncio.run(run())


def test_new344_titles_scope_hides_body(ab_env):  # noqa: F811
    """titles 范围：外部访问者只拿到标题目录（无正文/无选段）。"""
    client = ab_env["client"]
    refs = _seed_two_entries(ab_env)
    created = client.post(
        LINKS_PATH,
        json={"title": "每周目录", "scope": "titles", "entryRefs": refs},
        headers=ab_env["a"],
    )
    assert created.status_code == 201, created.text
    token = created.json()["token"]
    assert created.json()["path"] == f"/shares/{token}"

    public = client.get(f"/shares/{token}")
    assert public.status_code == 200, public.text
    payload = public.json()
    assert payload["scope"] == "titles"
    assert [item["title"] for item in payload["items"]] == [
        "公开安全公告",
        "第二篇：目录条目",
    ]
    flat = str(payload)
    assert "正文内容" not in flat and "excerpt" not in payload["items"][0]
    assert set(payload["neverIncluded"]) >= {"私人笔记", "标注"}

    # 预览与公开访问同一渲染（所见即所发）。
    link_id = created.json()["id"]
    preview = client.get(f"{LINKS_PATH}/{link_id}/preview", headers=ab_env["a"])
    assert preview.status_code == 200
    assert preview.json()["items"] == payload["items"]

    # token 只存哈希：清单与预览绝不含明文。
    listing = client.get(LINKS_PATH, headers=ab_env["a"]).json()
    assert token not in str(listing)


def test_new344_excerpt_scope_truncates_honestly(ab_env):  # noqa: F811
    client = ab_env["client"]
    refs = _seed_two_entries(ab_env)
    created = client.post(
        LINKS_PATH,
        json={
            "title": "选段预览",
            "scope": "excerpt",
            "entryRefs": refs[:1],
            "excerptChars": 40,
        },
        headers=ab_env["a"],
    )
    assert created.status_code == 201
    payload = client.get(f"/shares/{created.json()['token']}").json()
    item = payload["items"][0]
    assert len(item["excerpt"]) == 40
    assert item["excerptTruncated"] is True
    assert "contentText" not in item


def test_new344_full_scope_requires_device_trust(ab_env):  # noqa: F811
    """NEW-346 消费点：无信任 → 403 device_trust_required；授予后放行。"""
    client = ab_env["client"]
    refs = _seed_two_entries(ab_env)
    denied = client.post(
        LINKS_PATH,
        json={"title": "全文发布", "scope": "full", "entryRefs": refs[:1]},
        headers=ab_env["a"],
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["type"] == "device_trust_required"

    _grant_trust(ab_env, ab_env["a"])
    allowed = client.post(
        LINKS_PATH,
        json={"title": "全文发布", "scope": "full", "entryRefs": refs[:1]},
        headers=ab_env["a"],
    )
    assert allowed.status_code == 201, allowed.text
    payload = client.get(f"/shares/{allowed.json()['token']}").json()
    assert "这是可以完整公开的第一段正文" in payload["items"][0]["contentText"]


def test_new344_revoke_and_ab_isolation(ab_env):  # noqa: F811
    client = ab_env["client"]
    refs = _seed_two_entries(ab_env)
    created = client.post(
        LINKS_PATH,
        json={"title": "将撤销", "scope": "titles", "entryRefs": refs},
        headers=ab_env["a"],
    )
    link_id = created.json()["id"]
    token = created.json()["token"]
    assert client.get(f"/shares/{token}").status_code == 200

    # B 撤不掉 A 的链接（404 不泄露）。
    forbidden = client.post(f"{LINKS_PATH}/{link_id}/revoke", headers=ab_env["b"])
    assert forbidden.status_code == 404
    b_listing = client.get(LINKS_PATH, headers=ab_env["b"]).json()["items"]
    assert all(item["id"] != link_id for item in b_listing)

    revoked = client.post(f"{LINKS_PATH}/{link_id}/revoke", headers=ab_env["a"])
    assert revoked.status_code == 200
    assert client.get(f"/shares/{token}").status_code == 404
    again = client.post(f"{LINKS_PATH}/{link_id}/revoke", headers=ab_env["a"])
    assert again.status_code == 404


def test_new344_validation_and_unknown_token(ab_env):  # noqa: F811
    client = ab_env["client"]
    bad_scope = client.post(
        LINKS_PATH,
        json={"title": "x", "scope": "everything", "entryRefs": ["r"]},
        headers=ab_env["a"],
    )
    assert bad_scope.status_code == 422
    bad_chars = client.post(
        LINKS_PATH,
        json={
            "title": "x",
            "scope": "excerpt",
            "entryRefs": ["r"],
            "excerptChars": 5,
        },
        headers=ab_env["a"],
    )
    assert bad_chars.status_code == 422
    assert client.get("/shares/not-a-real-token").status_code == 404
