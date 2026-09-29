"""NEW-317 剪藏重复合并 — URL 变体分组、选段/版本保留、软删、A/B 隔离。"""

import asyncio
import uuid as _uuid

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册

MAIN_URL = "https://site.example/post/deep-dive"
VARIANT_URL = MAIN_URL + "?utm_source=news"
OTHER_URL = "https://site.example/other/story"


def _seed_clip(ab_env, who: str, url: str, *, title: str, revised: str | None = None) -> str:  # noqa: F811
    clip_uuid = str(_uuid.uuid4())

    async def seed():
        from lumirss.user_scope import user_context

        with user_context(ab_env[who]["userId"]):
            db = ab_env["app"].state.db
            await db.migrate()
            await db.execute(
                "INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'clip', '2026-09-01T00:00:00Z')",
                (clip_uuid,),
            )
            await db.execute(
                "INSERT INTO library_clips (item_uuid, url, title, byline, content_html, content_text, revised_content_html, revised_note, revised_at, fetched_at, created_at)"
                " VALUES (?, ?, ?, NULL, '<p>正文</p>', '正文', ?, ?, ?, '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')",
                (clip_uuid, url, title, revised, revised, "2026-09-01T00:00:01Z" if revised else None),
            )

    asyncio.run(seed())
    return f"library:{clip_uuid}"


def _seed_selection(ab_env, who: str, clip_ref: str, text: str) -> None:  # noqa: F811
    clip_uuid = clip_ref.split(":", 1)[1]

    async def seed():
        from lumirss.user_scope import user_context

        with user_context(ab_env[who]["userId"]):
            db = ab_env["app"].state.db
            await db.migrate()
            await db.execute(
                "INSERT INTO clip_selections (id, package_id, url, page_title, clip_item_uuid, seq, text, note, created_at)"
                " VALUES (?, ?, 'https://x.example', '页', ?, 0, ?, '', '2026-09-02T00:00:00Z')",
                (str(_uuid.uuid4()), str(_uuid.uuid4()), clip_uuid, text),
            )

    asyncio.run(seed())


def test_new317_groups_url_variants_and_merge_carries_selections_versions(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    kept = _seed_clip(ab_env, "a", MAIN_URL, title="主剪藏", revised=None)
    variant = _seed_clip(ab_env, "a", VARIANT_URL, title="带追踪参数的重复剪藏", revised="<p>被并入侧的修订版</p>")
    other = _seed_clip(ab_env, "a", OTHER_URL, title="不同页不算重复")
    _seed_selection(ab_env, "a", variant, "被并入侧的重要选段")

    # 分组：主剪藏 + 追踪参数变体 = 一组；不同页不成组
    groups = client.get("/api/v1/library/clip-duplicates", headers=a).json()
    assert groups["groupCount"] == 1
    group_refs = {i["ref"] for i in groups["groups"][0]["items"]}
    assert group_refs == {kept, variant}

    # 跨组合并 → 422（防错并）
    cross = client.post(
        "/api/v1/library/clips/merge",
        json={"keepRef": kept, "mergeRefs": [other], "metaPolicy": "kept"},
        headers=a,
    )
    assert cross.status_code == 422

    # 合并：metaPolicy=newest → 保留侧标题取组内最新（这里是被并入侧）
    merged = client.post(
        "/api/v1/library/clips/merge",
        json={"keepRef": kept, "mergeRefs": [variant], "metaPolicy": "newest"},
        headers=a,
    )
    assert merged.status_code == 200, merged.text
    result = merged.json()
    assert result["carriedSelections"] == 1
    assert result["carriedRevision"] == 1

    async def read_rows():
        from lumirss.user_scope import user_context

        with user_context(a["userId"]):
            db = ab_env["app"].state.db
            keep_row = await db.fetch_one(
                "SELECT title, revised_content_html, deleted_at IS NOT NULL AS gone FROM library_clips c JOIN library_items i ON i.uuid = c.item_uuid WHERE c.item_uuid = ?",
                (kept.split(":", 1)[1],),
            )
            merged_row = await db.fetch_one(
                "SELECT deleted_at IS NOT NULL AS gone FROM library_items WHERE uuid = ?",
                (variant.split(":", 1)[1],),
            )
            sel = await db.fetch_one(
                "SELECT clip_item_uuid FROM clip_selections WHERE text = '被并入侧的重要选段'"
            )
            return keep_row, merged_row, sel

    keep_row, merged_row, sel = asyncio.run(read_rows())
    assert keep_row is not None and keep_row["gone"] == 0
    assert keep_row["title"] == "带追踪参数的重复剪藏"  # newest 元数据
    assert "被并入侧的修订版" in str(keep_row["revised_content_html"])  # 版本保留
    assert merged_row is not None and merged_row["gone"] == 1  # 软删（回收站可恢复）
    assert sel is not None and sel["clip_item_uuid"] == kept.split(":", 1)[1]  # 选段重指向

    # 合并后组里只剩保留侧一条
    after = client.get("/api/v1/library/clip-duplicates", headers=a).json()
    assert after["groupCount"] == 0

    # 台账只追加
    merges = client.get("/api/v1/library/clip-duplicates/merges", headers=a).json()["merges"]
    assert len(merges) == 1 and merges[0]["metaPolicy"] == "newest"

    # metaPolicy 校验
    bad = client.post(
        "/api/v1/library/clips/merge",
        json={"keepRef": kept, "mergeRefs": [kept], "metaPolicy": "kept"},
        headers=a,
    )
    assert bad.status_code == 422  # 保留侧不能同时在 mergeRefs


def test_new317_missing_clip_and_policy_validation(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    kept = _seed_clip(ab_env, "a", MAIN_URL, title="主剪藏")
    missing = client.post(
        "/api/v1/library/clips/merge",
        json={
            "keepRef": kept,
            "mergeRefs": [f"library:{_uuid.uuid4()}"],
            "metaPolicy": "kept",
        },
        headers=a,
    )
    assert missing.status_code == 404

    bad_policy = client.post(
        "/api/v1/library/clips/merge",
        json={"keepRef": kept, "mergeRefs": [f"library:{_uuid.uuid4()}"], "metaPolicy": "random"},
        headers=a,
    )
    # pydantic pattern 拦截 → 422（FastAPI 校验错误）
    assert bad_policy.status_code == 422


def test_new317_per_user_isolation_between_accounts(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    a_main = _seed_clip(ab_env, "a", MAIN_URL, title="A 的主剪藏")
    a_variant = _seed_clip(ab_env, "a", VARIANT_URL, title="A 的变体")
    b_clip = _seed_clip(ab_env, "b", MAIN_URL + "?utm_source=b", title="B 的剪藏")

    # B 的分组里看不到 A 的组
    groups = client.get("/api/v1/library/clip-duplicates", headers=b).json()
    all_b_refs = {i["ref"] for g in groups["groups"] for i in g["items"]}
    assert a_main not in all_b_refs and a_variant not in all_b_refs

    # B 不能把 A 的剪藏并进自己的组（A 剪藏在 B 库中不存在 → 404）
    cross_user = client.post(
        "/api/v1/library/clips/merge",
        json={"keepRef": b_clip, "mergeRefs": [a_variant], "metaPolicy": "kept"},
        headers=b,
    )
    assert cross_user.status_code == 404

    # A 正常合并自己的组，B 的剪藏不受影响
    ok = client.post(
        "/api/v1/library/clips/merge",
        json={"keepRef": a_main, "mergeRefs": [a_variant], "metaPolicy": "kept"},
        headers=a,
    )
    assert ok.status_code == 200

    async def b_alive():
        from lumirss.user_scope import user_context

        with user_context(b["userId"]):
            db = ab_env["app"].state.db
            row = await db.fetch_one(
                "SELECT deleted_at FROM library_items WHERE uuid = ?",
                (b_clip.split(":", 1)[1],),
            )
            return row is not None and row["deleted_at"] is None

    assert asyncio.run(b_alive()) is True  # B 的剪藏存活：deleted_at 仍为 NULL
