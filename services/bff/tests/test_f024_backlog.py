"""F024 积压整理助手 —— count/apply 一致、保护项、token 过期与幂等。"""

import asyncio

from lumirss.entryref import encode_entry_ref


def run(coroutine):
    return asyncio.run(coroutine)


class FakeStateAdapter:
    """记录 set_entry_state 调用（FreshRSS 侧断言用）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool | None, bool | None]] = []

    async def set_entry_state(self, item_id, read=None, starred=None):
        self.calls.append((str(item_id), read, starred))


def _seed(app, item_id, *, read=0, starred=0, published_at, title="t"):
    entry_ref = encode_entry_ref(item_id)
    run(
        app.state.db.execute(
            "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, 'https://f.example/rss', '源', ?, '', 'u', '', ?, ?, ?, 0)",
            (item_id, entry_ref, title, published_at, read, starred),
        )
    )
    return entry_ref


def test_f024_preview_count_matches_apply_and_protections_hold(client):
    app = client.app
    run(app.state.db.migrate())
    old = "2026-01-01T00:00:00Z"
    recent = "2026-09-18T00:00:00Z"
    _ = recent  # 未用变量刻意保留（样本时间）
    _ref1 = f"rss:{_seed(app, "b1", published_at=old)}"
    _ref2 = f"rss:{_seed(app, "b2", published_at=old)}"
    # 保护项：加星 / 稍后读（reserved workspace 成员）/ 已读
    _seed(app, "b3", published_at=old, starred=1)
    _seed(app, "b4", published_at=old, read=1)
    e_later = _seed(app, "b5", published_at=old)
    run(
        app.state.db.execute(
            "INSERT INTO workspace_items (workspace_id, item_ref, position, added_at) VALUES ('read-later', ?, 1, '2026-09-19T00:00:00Z')",
            (f"rss:{e_later}",),
        )
    )

    preview = client.post(
        "/api/v1/entries/backlog-preview",
        json={"olderThanDays": 30, "excludeStarred": False, "excludeReadLater": False},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["count"] == 2  # 服务端真实计数（非样本长度）
    assert {item["ref"] for item in body["sample"]} == {_ref1, _ref2}
    assert body["effectiveExclusions"] == ["starred", "read-later"]  # 传 false 也保护

    fake = FakeStateAdapter()
    app.state.freshrss_adapter = fake
    try:
        applied = client.post(
            "/api/v1/entries/backlog-apply",
            json={
                "olderThanDays": 30,
                "excludeStarred": False,
                "excludeReadLater": False,
                "confirmPreviewToken": body["confirmPreviewToken"],
            },
        )
        assert applied.status_code == 200, applied.text
        result = applied.json()
        assert result["applied"] == 2
        assert result["failed"] == []
        # FreshRSS 侧断言：保护项从未被写
        marked = {item_id for item_id, read, _ in fake.calls if read is True}
        assert marked == {"b1", "b2"}  # noqa: 直呼种子 id（测试数据）
        assert all(c[0] != "b3" and c[0] != "b5" for c in fake.calls)
        # 投影镜像：候选行已置读
        rows = run(
            app.state.db.fetch_all(
                "SELECT item_id, read FROM search_entries WHERE item_id IN ('b1','b2')", ()
            )
        )
        assert all(int(row["read"]) == 1 for row in rows)
    finally:
        app.state.freshrss_adapter = None

    # 重复 apply（同 token、同条件）→ 幂等，第二次 0
    second = client.post(
        "/api/v1/entries/backlog-apply",
        json={
            "olderThanDays": 30,
            "confirmPreviewToken": body["confirmPreviewToken"],
        },
    )
    assert second.status_code == 200
    assert second.json()["applied"] == 0


def test_f024_token_expiry_and_condition_drift(client):
    app = client.app
    run(app.state.db.migrate())
    _seed(app, "c1", published_at="2026-01-01T00:00:00Z")

    preview = client.post(
        "/api/v1/entries/backlog-preview",
        json={"olderThanDays": 30, "feedUrl": "https://f.example/rss"},
    )
    token = preview.json()["confirmPreviewToken"]

    # 条件漂移（缺 feedUrl）→ 409
    drift = client.post(
        "/api/v1/entries/backlog-apply",
        json={"olderThanDays": 30, "confirmPreviewToken": token},
    )
    assert drift.status_code == 409
    assert drift.json()["error"]["type"] == "backlog_conflict"

    # token 过期 → 409
    from lumirss.backlog import _tokens

    stale_condition, _ = _tokens[token]
    _tokens[token] = (stale_condition, 0.0)  # 置为已过期
    expired = client.post(
        "/api/v1/entries/backlog-apply",
        json={
            "olderThanDays": 30,
            "feedUrl": "https://f.example/rss",
            "confirmPreviewToken": token,
        },
    )
    assert expired.status_code == 409

    # 伪造 token → 409
    forged = client.post(
        "/api/v1/entries/backlog-apply",
        json={
            "olderThanDays": 30,
            "confirmPreviewToken": "forged-token-000000000",
        },
    )
    assert forged.status_code == 409


def test_f024_partial_failures_reported(client):
    app = client.app
    run(app.state.db.migrate())
    _seed(app, "d1", published_at="2026-01-01T00:00:00Z")
    _seed(app, "d2", published_at="2026-01-02T00:00:00Z")

    class HalfBrokenAdapter(FakeStateAdapter):
        async def set_entry_state(self, item_id, read=None, starred=None):
            if str(item_id).endswith("d1"):
                raise RuntimeError("上游拒绝")
            return await super().set_entry_state(item_id, read=read, starred=starred)

    preview = client.post(
        "/api/v1/entries/backlog-preview", json={"olderThanDays": 30}
    )
    token = preview.json()["confirmPreviewToken"]
    fake = HalfBrokenAdapter()
    app.state.freshrss_adapter = fake
    try:
        applied = client.post(
            "/api/v1/entries/backlog-apply",
            json={
                "olderThanDays": 30,
                "confirmPreviewToken": token,
            },
        )
        assert applied.status_code == 200
        result = applied.json()
        assert result["applied"] == 1
        assert len(result["failed"]) == 1
        assert result["failed"][0]["ref"].endswith(encode_entry_ref("d1"))
    finally:
        app.state.freshrss_adapter = None
