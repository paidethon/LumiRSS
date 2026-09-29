"""NEW-312 网页选区剪藏包 — 用户提交选区的保真保存、按页检索、A/B 隔离。"""

import asyncio
import uuid as _uuid

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册

PAGE_URL = "https://reader.example/articles/why-rss"


DEFAULT_SELECTIONS = [
    {"text": "RSS 的价值在于所有权：订阅者决定时间线。", "note": "核心论点"},
    {"text": "算法推荐把选择权交给了平台。"},
]


def _create(client, headers, *, selections=None, clip_ref=None, url=PAGE_URL):
    body: dict = {
        "url": url,
        "pageTitle": "为什么 RSS 仍然重要",
        "selections": DEFAULT_SELECTIONS if selections is None else selections,
    }
    if clip_ref is not None:
        body["clipRef"] = clip_ref
    return client.post("/api/v1/library/clip-selections", json=body, headers=headers)


def test_new312_selection_package_preserves_user_selections_without_fetch(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    created = _create(client, a)
    assert created.status_code == 201, created.text
    package = created.json()
    assert package["url"] == PAGE_URL
    assert package["pageTitle"] == "为什么 RSS 仍然重要"
    assert package["clipRef"] is None
    assert [s["text"] for s in package["selections"]] == [
        "RSS 的价值在于所有权：订阅者决定时间线。",
        "算法推荐把选择权交给了平台。",
    ]
    assert package["selections"][0]["note"] == "核心论点"

    # 单包可读、按页可查（另一 URL 无结果）
    got = client.get(f"/api/v1/library/clip-selections/{package['id']}", headers=a)
    assert got.status_code == 200
    assert got.json()["id"] == package["id"]
    by_page = client.get(
        "/api/v1/library/clip-selections", params={"url": PAGE_URL}, headers=a
    ).json()["packages"]
    assert len(by_page) == 1
    none = client.get(
        "/api/v1/library/clip-selections",
        params={"url": "https://other.example/x"},
        headers=a,
    ).json()["packages"]
    assert none == []

    # 删除后 404（诚实）
    assert (
        client.delete(f"/api/v1/library/clip-selections/{package['id']}", headers=a).status_code
        == 204
    )
    assert (
        client.get(f"/api/v1/library/clip-selections/{package['id']}", headers=a).status_code
        == 404
    )


def test_new312_clip_ref_linkage_validated_server_side(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]

    # 直接落一条真实剪藏（per-user 库）用于挂接
    clip_uuid = str(_uuid.uuid4())

    async def seed():
        from lumirss.user_scope import user_context

        with user_context(a["userId"]):
            db = ab_env["app"].state.db
            await db.migrate()
            await db.execute(
                "INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'clip', '2026-09-01T00:00:00Z')",
                (clip_uuid,),
            )
            await db.execute(
                "INSERT INTO library_clips (item_uuid, url, title, byline, content_html, content_text, fetched_at, created_at)"
                " VALUES (?, ?, '为什么 RSS 仍然重要', NULL, '<p>正文</p>', '正文', '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')",
                (clip_uuid, PAGE_URL),
            )

    asyncio.run(seed())

    linked = _create(client, a, clip_ref=f"library:{clip_uuid}")
    assert linked.status_code == 201, linked.text
    assert linked.json()["clipRef"] == f"library:{clip_uuid}"

    # 不存在的剪藏 → 404，绝不静默丢链接
    missing = _create(client, a, clip_ref="library:00000000-0000-4000-8000-000000000000")
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "clip_not_found"

    # 非 library: 前缀 → 422
    bad = _create(client, a, clip_ref="rss:whatever")
    assert bad.status_code == 422


def test_new312_payload_validation_422(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    # 非法 scheme
    assert (
        _create(client, a, url="javascript:alert(1)").status_code == 422
    )
    # 单段超长
    long_pkg = _create(client, a, selections=[{"text": "长" * 2001}])
    assert long_pkg.status_code == 422
    # 空选区
    empty = _create(client, a, selections=[])
    assert empty.status_code == 422
    # 超过 20 段
    too_many = _create(
        client, a, selections=[{"text": f"段{i}"} for i in range(21)]
    )
    assert too_many.status_code == 422


def test_new312_per_user_isolation_between_accounts(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    created = _create(client, a)
    package_id = created.json()["id"]

    # B 看不到 A 的剪藏包；删 A 的包 → 404
    assert client.get("/api/v1/library/clip-selections", headers=b).json()["packages"] == []
    assert (
        client.get(f"/api/v1/library/clip-selections/{package_id}", headers=b).status_code
        == 404
    )
    assert (
        client.delete(f"/api/v1/library/clip-selections/{package_id}", headers=b).status_code
        == 404
    )
    # A 的数据原样
    assert len(client.get("/api/v1/library/clip-selections", headers=a).json()["packages"]) == 1

    # B 建自己的同 URL 包，互不串扰
    assert _create(client, b).status_code == 201
    a_packages = client.get("/api/v1/library/clip-selections", headers=a).json()["packages"]
    b_packages = client.get("/api/v1/library/clip-selections", headers=b).json()["packages"]
    assert len(a_packages) == 1 and len(b_packages) == 1
    assert a_packages[0]["id"] != b_packages[0]["id"]
