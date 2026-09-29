"""NEW-314 快照文字检索层 — 构建（原快照不变）、命中定位、A/B 隔离。

快照通过 AssetStore 真实落盘（临时目录），检索走真实 LIKE 路径。
"""

import asyncio

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册

SNAPSHOT_HTML = (
    "<html><head><title>离线快照</title></head><body>"
    "<h1>第一章 研究背景</h1>"
    "<p>分布式爬虫在过去十年成为主流采集方式。</p>"
    "<p>本节介绍背景与动机。</p>"
    "<h2>第二章 方法</h2>"
    "<li> RSSHub 把非 RSS 源转成标准订阅源。</li>"
    "<blockquote>引用：快照是用户保存的资产，不是缓存。</blockquote>"
    "</body></html>"
)


def _seed_snapshot(ab_env, who: str) -> str:  # noqa: F811
    """落一条真实快照（文件 + 行），返回 asset uuid。"""

    async def seed():
        from pathlib import Path

        from lumirss.library_assets import AssetStore
        from lumirss.user_scope import user_context

        with user_context(ab_env[who]["userId"]):
            app = ab_env["app"]
            db = app.state.db
            await db.migrate()
            # 与 deps._get_snapshot_store 同一根：users_root/<uid>/library/assets
            root = Path(app.state.users_root) / ab_env[who]["userId"] / "library" / "assets"
            store = AssetStore(db, root)
            record, _deduped = await store.save_snapshot(
                data=SNAPSHOT_HTML.encode("utf-8"),
                mime="text/html",
                url="https://docs.example/guide",
            )
            ab_env[f"_asset_root_{who}"] = root
            ab_env[f"_asset_path_{who}"] = record.path

    asyncio.run(seed())
    return _asset_uuid(ab_env, who)


def _asset_uuid(ab_env, who: str) -> str:  # noqa: F811
    async def read():
        from lumirss.user_scope import user_context

        with user_context(ab_env[who]["userId"]):
            db = ab_env["app"].state.db
            row = await db.fetch_one(
                "SELECT uuid FROM library_assets WHERE path = ?",
                (ab_env[f"_asset_path_{who}"],),
            )
            assert row is not None
            return str(row["uuid"])

    return asyncio.run(read())


def _routes(asset_uuid: str) -> dict[str, str]:
    return {
        "build": f"/api/v1/library/snapshots/{asset_uuid}/text-layer",
        "search": f"/api/v1/library/snapshots/{asset_uuid}/text-layer",
        "status": f"/api/v1/library/snapshots/{asset_uuid}/text-layer/status",
    }


def _snapshot_bytes(ab_env, who: str, asset_uuid: str) -> tuple[bytes, str]:  # noqa: F811
    async def read():
        from lumirss.user_scope import user_context

        with user_context(ab_env[who]["userId"]):
            db = ab_env["app"].state.db
            row = await db.fetch_one(
                "SELECT path, sha256 FROM library_assets WHERE uuid = ?", (asset_uuid,)
            )
            assert row is not None
            path = ab_env[f"_asset_root_{who}"] / str(row["path"])
            return path.read_bytes(), str(row["sha256"])

    return asyncio.run(read())


def test_new314_build_text_layer_and_locate_hits_without_touching_snapshot(ab_env):  # noqa: F811
    import hashlib

    client, a = ab_env["client"], ab_env["a"]
    asset_uuid = _seed_snapshot(ab_env, "a")
    routes = _routes(asset_uuid)
    before_bytes, before_sha = _snapshot_bytes(ab_env, "a", asset_uuid)

    # 未构建先搜 → 404（提示构建，绝不返回空结果假装搜过）
    early = client.get(routes["search"], params={"q": "爬虫"}, headers=a)
    assert early.status_code == 404
    assert early.json()["error"]["type"] == "text_layer_not_found"

    built = client.post(routes["build"], headers=a)
    assert built.status_code == 201, built.text
    body = built.json()
    # 标题作锚不重复成块：两个 p + li + blockquote = 4 块
    assert body["blockCount"] == 4
    assert body["assetRef"] == f"library:{asset_uuid}"

    status = client.get(routes["status"], headers=a).json()
    assert status["built"] is True
    assert status["blockCount"] == body["blockCount"]

    # 命中定位：seq + anchor（最近的上级标题）
    hits = client.get(routes["search"], params={"q": "爬虫"}, headers=a).json()
    assert hits["hitCount"] == 1
    hit = hits["hits"][0]
    assert "分布式爬虫" in hit["text"]
    assert hit["anchor"] == "第一章 研究背景"

    li_hits = client.get(routes["search"], params={"q": "RSSHub"}, headers=a).json()
    assert li_hits["hits"][0]["anchor"] == "第二章 方法"

    # LIKE 通配符按字面处理：搜 “%” 无命中（不崩溃、不全表匹配）
    wild = client.get(routes["search"], params={"q": "%"}, headers=a).json()
    assert wild["hits"] == []

    # 原快照字节与 sha256 完全不变
    after_bytes, after_sha = _snapshot_bytes(ab_env, "a", asset_uuid)
    assert after_bytes == before_bytes
    assert after_sha == before_sha
    assert hashlib.sha256(after_bytes).hexdigest() == before_sha

    # 重建是幂等替换（不重复叠加块）
    rebuilt = client.post(routes["build"], headers=a)
    assert rebuilt.status_code == 201
    assert rebuilt.json()["blockCount"] == body["blockCount"]

    # 空搜索词 → 400
    assert (
        client.get(routes["search"], params={"q": "  "}, headers=a).status_code == 400
    )


def test_new314_per_user_isolation_between_accounts(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    asset_uuid = _seed_snapshot(ab_env, "a")
    routes = _routes(asset_uuid)

    assert client.post(routes["build"], headers=a).status_code == 201

    # B 视角：A 的快照不存在（既不能构建也不能搜索）
    assert client.post(routes["build"], headers=b).status_code == 404
    assert client.get(routes["search"], params={"q": "爬虫"}, headers=b).status_code == 404

    # B 建自己的快照并构建，与 A 互不可见
    b_asset = _seed_snapshot(ab_env, "b")
    b_routes = _routes(b_asset)
    assert client.post(b_routes["build"], headers=b).status_code == 201
    b_status = client.get(b_routes["status"], headers=b).json()
    assert b_status["built"] is True
