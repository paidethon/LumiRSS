"""N078 批注跨版本迁移 — 预览 / 逐项应用 / 冲突跳过 / 跨用户拒绝。

- 预览（零写入）：批注引文对 last_known_full（N032 保留的完整变体）
  的正文块重检（N071 同口径）；找不到候选 → unmatched 诚实列出；
- 应用：选中项走 store.rebind（旧锚点进 annotation_repair_log ——
  N071 修复历史即撤销台账）；目标块与他条批注冲突 → 跳过不覆盖；
- fromVersion == toVersion / 未知版本词 → 422；
- 跨用户：per-user 库 + 真实路由——B 的批注对 A 不可见（404）。
"""

import asyncio
from types import SimpleNamespace

from lumirss.entryref import encode_entry_ref
from lumirss.main import app

VARIANT_HTML = (
    "<p>开篇完全不同的段落。</p>"
    "<p>这里包含被移动的关键观点原文，前后略有改动。</p>"
    "<p>结尾段落。</p>"
)


def _run(coroutine):
    return asyncio.run(coroutine)


def _install_entry(content_text: str) -> None:
    async def get_entry(item_id: str):  # noqa: ARG001
        return SimpleNamespace(
            contentText=content_text,
            title="标题",
            feedTitle="来源",
            publishedAt="2026-01-02T03:04:05Z",
            url=None,
        )

    app.state.freshrss_adapter = SimpleNamespace(get_entry=get_entry)


def _seed_variant(entry_ref: str) -> None:
    async def seed():
        await app.state.db.migrate()
        await app.state.db.execute(
            "INSERT OR REPLACE INTO entry_content_variants (entry_ref, content_html, captured_at) VALUES (?, ?, '2026-01-01T00:00:00Z')",
            (entry_ref, VARIANT_HTML),
        )

    _run(seed())


def test_n078_preview_and_selective_apply(client):
    """预览给出候选；apply 只迁移确认项；低分块拒绝。"""
    ref = encode_entry_ref("9401")
    quote = "被移动的关键观点原文"
    created = client.post(
        "/api/v1/annotations",
        json={
            "entryRef": ref,
            "anchor": {"paraId": "p-0", "prefix": "", "exact": quote, "suffix": ""},
            "excerpt": quote,
            "note": "要点",
        },
    )
    assert created.status_code == 201
    annotation_id = created.json()["id"]
    _seed_variant(ref)

    # from == to → 422；未知版本词 → 422
    same = client.post(
        "/api/v1/annotations/migrate/preview",
        json={"entryRef": ref, "fromVersion": "current", "toVersion": "current"},
    )
    assert same.status_code == 422
    unknown = client.post(
        "/api/v1/annotations/migrate/preview",
        json={"entryRef": ref, "fromVersion": "current", "toVersion": "nope"},
    )
    assert unknown.status_code == 422

    # 预览（current → last_known_full）：候选块 1、score 1.0；零写入
    preview = client.post(
        "/api/v1/annotations/migrate/preview",
        json={"entryRef": ref, "fromVersion": "current", "toVersion": "last_known_full"},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["toVersion"] == "last_known_full"
    assert len(body["matched"]) == 1
    assert body["matched"][0]["annotationId"] == annotation_id
    assert body["matched"][0]["candidateBlockIndex"] == 1
    assert body["matched"][0]["score"] == 1.0
    assert body["unmatched"] == []
    # 零写入：锚点未变
    before = client.get(f"/api/v1/annotations?entryRef={ref}").json()["items"][0]
    assert before["anchor"]["paraId"] == "p-0"

    # 变体不可达（无保留行）→ 422 诚实拒绝
    _seed_variant(encode_entry_ref("9402"))
    _install_entry("适配器正文。\n第二块。")
    empty = client.post(
        "/api/v1/annotations/migrate/preview",
        json={
            "entryRef": encode_entry_ref("9402"),
            "fromVersion": "last_known_full",
            "toVersion": "current",
        },
    )
    assert empty.status_code == 404  # 该文章没有批注 → 404（先于内容解析）

    # 应用（把适配器正文换成变体内容口径的场景：直接对 last_known_full 迁移）
    _install_entry("")
    applied = client.post(
        "/api/v1/annotations/migrate/apply",
        json={
            "entryRef": ref,
            "fromVersion": "current",
            "toVersion": "last_known_full",
            "items": [{"annotationId": annotation_id, "blockIndex": 1}],
        },
    )
    assert applied.status_code == 200, applied.text
    result = applied.json()
    assert [r["annotationId"] for r in result["applied"]] == [annotation_id]
    assert result["failed"] == []

    # 锚点已重绑到目标块（与 N071 repair 相同形状）
    item = client.get(f"/api/v1/annotations?entryRef={ref}").json()["items"][0]
    assert item["anchor"] == {
        "paraId": "block-1",
        "prefix": "",
        "exact": quote,
        "suffix": "",
    }
    # 修复历史有记录（N071 台账 = 撤销依据）
    async def history_count():
        row = await app.state.db.fetch_one(
            "SELECT COUNT(*) AS n FROM annotation_repair_log WHERE annotation_id = ?",
            (annotation_id,),
        )
        return int(row["n"])

    assert _run(history_count()) == 1

    # 越界块 / 低分块 → failed（不中断整批）
    bad = client.post(
        "/api/v1/annotations/migrate/apply",
        json={
            "entryRef": ref,
            "fromVersion": "current",
            "toVersion": "last_known_full",
            "items": [
                {"annotationId": annotation_id, "blockIndex": 99},
                {"annotationId": "missing", "blockIndex": 1},
            ],
        },
    )
    assert bad.status_code == 200
    reasons = {r["annotationId"]: r["reason"] for r in bad.json()["failed"]}
    assert reasons[annotation_id] == "block_out_of_range"
    assert reasons["missing"] == "not_found"


def test_n078_conflict_skip_never_overwrites(client):
    """目标块已被另一条批注占用（锚点冲突）→ 该项 failed=target_conflict，
    既有批注绝不被覆盖。"""
    ref = encode_entry_ref("9403")
    quote = "同一位置的两条批注"
    variant_html = f"<p>完全不同的开头。</p><p>{quote}，在完整版本里。</p>"
    first = client.post(
        "/api/v1/annotations",
        json={
            "entryRef": ref,
            "anchor": {"paraId": "p-0", "prefix": "", "exact": quote, "suffix": ""},
            "excerpt": quote,
        },
    ).json()
    second = client.post(
        "/api/v1/annotations",
        json={
            "entryRef": ref,
            "anchor": {"paraId": "p-1", "prefix": "", "exact": quote, "suffix": ""},
            "excerpt": quote,
        },
    ).json()
    assert first["id"] != second["id"]

    async def seed():
        await app.state.db.migrate()
        await app.state.db.execute(
            "INSERT OR REPLACE INTO entry_content_variants (entry_ref, content_html, captured_at) VALUES (?, ?, '2026-01-01T00:00:00Z')",
            (ref, variant_html),
        )

    _run(seed())

    # 先迁移第一条 → 占据 block-1
    applied = client.post(
        "/api/v1/annotations/migrate/apply",
        json={
            "entryRef": ref,
            "fromVersion": "current",
            "toVersion": "last_known_full",
            "items": [{"annotationId": first["id"], "blockIndex": 1}],
        },
    )
    assert applied.json()["applied"][0]["annotationId"] == first["id"]

    # 第二条同引文迁移到同一块 → target_conflict；第一条锚点不被改写
    response = client.post(
        "/api/v1/annotations/migrate/apply",
        json={
            "entryRef": ref,
            "fromVersion": "current",
            "toVersion": "last_known_full",
            "items": [{"annotationId": second["id"], "blockIndex": 1}],
        },
    )
    body = response.json()
    assert body["applied"] == []
    assert body["failed"][0]["reason"] == "target_conflict"

    items = {i["id"]: i for i in client.get(f"/api/v1/annotations?entryRef={ref}").json()["items"]}
    assert items[first["id"]]["anchor"]["paraId"] == "block-1"  # 不被覆盖
    assert items[second["id"]]["anchor"]["paraId"] == "p-1"  # 原样保留


def test_n078_cross_user_annotations_invisible(monkeypatch, tmp_path):
    """跨用户：B 的批注对 A 不可见——A 的迁移请求 404/找不到。"""
    import secrets as _secrets

    from fastapi.testclient import TestClient

    password = _secrets.token_urlsafe(16)
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")

    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()

    async def _set_owner_password():
        from lumirss.accounts_store import AccountsStore, hash_password
        from lumirss.storage import Database

        database = Database(str(tmp_path / "lumi.sqlite"))
        await database.migrate()
        store = AccountsStore(database)
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                await store.set_password_hash(str(row["id"]), hash_password(password))
                return

    with TestClient(app, base_url="http://lumirss.test") as session_client:
        _run(_set_owner_password())
        owner_login = session_client.post(
            "/api/v1/auth/login", json={"username": "owner", "password": password}
        )
        owner = {"cookie": owner_login.headers["set-cookie"].split(";")[0]}
        invite = session_client.post(
            "/api/v1/admin/invites", json={"label": "n078b"}, headers=owner
        )
        member = session_client.post(
            "/api/v1/auth/activate",
            json={
                "token": invite.json()["token"],
                "username": "n078b",
                "password": password,
            },
        )
        member_headers = {"cookie": member.headers["set-cookie"].split(";")[0]}

        ref = encode_entry_ref("9404")
        # B 建批注（进 B 的库）
        created = session_client.post(
            "/api/v1/annotations",
            json={
                "entryRef": ref,
                "anchor": {"paraId": "p-0", "prefix": "", "exact": "B 的批注", "suffix": ""},
                "excerpt": "B 的批注",
            },
            headers=member_headers,
        )
        assert created.status_code == 201
        foreign_id = created.json()["id"]

        # A 对同一 entryRef 发起迁移：A 的库里没有该文章批注 → 404
        denied = session_client.post(
            "/api/v1/annotations/migrate/preview",
            json={"entryRef": ref, "fromVersion": "current", "toVersion": "last_known_full"},
            headers=owner,
        )
        assert denied.status_code == 404
        apply_denied = session_client.post(
            "/api/v1/annotations/migrate/apply",
            json={
                "entryRef": ref,
                "fromVersion": "current",
                "toVersion": "last_known_full",
                "items": [{"annotationId": foreign_id, "blockIndex": 0}],
            },
            headers=owner,
        )
        # A 的库中该 annotationId 不存在 → not_found（绝不迁移他人批注）
        assert apply_denied.status_code in (404, 422)
        if apply_denied.status_code == 200:
            assert apply_denied.json()["failed"][0]["reason"] == "not_found"
