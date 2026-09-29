"""NEW-225 积压处理向导（服务端）。

- 范围预览：按来源真实 COUNT + ≤3 抽样；「审过保留」的来源被排除并
  如实标注 keptDecisionsExcluded；候选口径与 N049 一致（未读 + 未加星
  + 不在稍后读 + 账龄下限）；
- keep 决策幂等（来源+范围唯一锚点）；
- 归档两段式：preview token（30s）→ apply 必带（缺失/漂移 → 409），
  绝不默认全标已读；执行走 set-read 管线（Fake 适配器记录调用），
  实际成功的 refs 进撤销台账（undoAvailable）；
- stage 分批阅读：必须由用户指定时段；已有时段归属的跳过如实计数。
"""

from new2xx_ab import ab_env  # noqa: F401,F811


class FakeStateAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool | None, bool | None]] = []

    async def set_entry_state(self, item_id, read=None, starred=None):
        self.calls.append((str(item_id), read, starred))


class FakeSearch:
    def __init__(self, app) -> None:
        self._db = app.state.db
        self.read_refs: list[str] = []

    async def set_entry_read(self, entry_ref: str, read: bool) -> None:
        await self._db.execute(
            "UPDATE search_entries SET read = ? WHERE entry_ref = ?",
            (1 if read else 0, entry_ref),
        )
        if read:
            self.read_refs.append(entry_ref)


def _plant_fakes(ab_env) -> FakeStateAdapter:
    fake = FakeStateAdapter()
    ab_env["app"].state.freshrss_adapter = fake
    ab_env["app"].state.search_service = FakeSearch(ab_env["app"])
    return fake


def _seed_old(ab_env, who: str, item_id: str, feed: str, *, read=0, starred=0):
    from new2xx_ab import seed_entry as _seed

    # seed_entry 固定 feed_url；这里直接扩展：插入后改 feed_url。
    ref = _seed(ab_env, who, item_id, title=item_id, read=read)
    import asyncio

    from lumirss.user_scope import user_context

    async def run():
        with user_context(ab_env[who]["userId"]):
            await ab_env["app"].state.db.execute(
                "UPDATE search_entries SET feed_url = ?, starred = ?"
                " WHERE entry_ref = ?",
                (feed, starred, ref.removeprefix("rss:")),
            )

    asyncio.run(run())
    return ref


def _old_published(ab_env, who: str, ref: str, published_at: str) -> None:
    import asyncio

    from lumirss.user_scope import user_context

    async def run():
        with user_context(ab_env[who]["userId"]):
            await ab_env["app"].state.db.execute(
                "UPDATE search_entries SET published_at = ? WHERE entry_ref = ?",
                (published_at, ref.removeprefix("rss:")),
            )

    asyncio.run(run())


def test_preview_groups_and_keep_exclusion(ab_env):  # noqa: F811
    client = ab_env["client"]
    _seed_old(ab_env, "a", "b1", "https://a.example/rss")
    _seed_old(ab_env, "a", "b2", "https://a.example/rss")
    _seed_old(ab_env, "a", "b3", "https://b.example/rss", starred=1)  # 保护
    # seed 的 published_at 默认 2026-09-20（约 8 天前）→ olderThanDays=7 命中。

    preview = client.post(
        "/api/v1/backlog/wizard/preview",
        json={"olderThanDays": 7},
        headers=ab_env["a"],
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    keys = {group["feedUrl"]: group for group in body["groups"]}
    assert set(keys) == {"https://a.example/rss"}
    assert keys["https://a.example/rss"]["unreadCount"] == 2
    assert len(keys["https://a.example/rss"]["sample"]) == 2
    assert "starred" in body["effectiveExclusions"]

    # keep a.example → 之后再预览排除该来源，keptDecisionsExcluded=1。
    keep = client.post(
        "/api/v1/backlog/wizard/keep",
        json={"feedUrl": "https://a.example/rss", "olderThanDays": 7, "note": "还想读"},
        headers=ab_env["a"],
    )
    assert keep.status_code == 200, keep.text
    again = client.post(
        "/api/v1/backlog/wizard/preview",
        json={"olderThanDays": 7},
        headers=ab_env["a"],
    )
    body2 = again.json()
    assert body2["groups"] == []
    assert body2["keptDecisionsExcluded"] == 1
    # keep 幂等（同来源同范围 upsert）。
    keep_again = client.post(
        "/api/v1/backlog/wizard/keep",
        json={"feedUrl": "https://a.example/rss", "olderThanDays": 7},
        headers=ab_env["a"],
    )
    assert keep_again.status_code == 200
    listed = client.get("/api/v1/backlog/wizard/keep", headers=ab_env["a"])
    assert listed.json()["items"][0]["note"] == "还想读"


def test_archive_two_phase_and_never_by_default(ab_env):  # noqa: F811
    client = ab_env["client"]
    fake = _plant_fakes(ab_env)
    _seed_old(ab_env, "a", "c1", "https://c.example/rss")
    _seed_old(ab_env, "a", "c2", "https://c.example/rss")

    # 没有预演的 apply（空 token）→ 409：绝不默认全标已读。
    naked = client.post(
        "/api/v1/backlog/wizard/archive-apply",
        json={"feedUrl": "https://c.example/rss", "olderThanDays": 7,
              "confirmToken": ""},
        headers=ab_env["a"],
    )
    assert naked.status_code == 409, naked.text
    assert naked.json()["error"]["type"] == "backlog_wizard_conflict"
    assert fake.calls == []

    # 条件漂移（换了 feedUrl）→ 409。
    preview = client.post(
        "/api/v1/backlog/wizard/archive-preview",
        json={"feedUrl": "https://c.example/rss", "olderThanDays": 7},
        headers=ab_env["a"],
    )
    assert preview.status_code == 200, preview.text
    token = preview.json()["confirmToken"]
    assert preview.json()["count"] == 2
    drifted = client.post(
        "/api/v1/backlog/wizard/archive-apply",
        json={"feedUrl": "https://other.example/rss", "olderThanDays": 7,
              "confirmToken": token},
        headers=ab_env["a"],
    )
    assert drifted.status_code == 409

    # 正确两段式：执行置读 + 台账。
    applied = client.post(
        "/api/v1/backlog/wizard/archive-apply",
        json={"feedUrl": "https://c.example/rss", "olderThanDays": 7,
              "confirmToken": token},
        headers=ab_env["a"],
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["applied"] == 2 and body["failed"] == 0
    assert body["undoAvailable"] is True and body["batchLogId"]
    assert len(fake.calls) == 2
    # token 30s 内可重放：重放时已全读 → applied=0（幂等收敛）。
    replay = client.post(
        "/api/v1/backlog/wizard/archive-apply",
        json={"feedUrl": "https://c.example/rss", "olderThanDays": 7,
              "confirmToken": token},
        headers=ab_env["a"],
    )
    assert replay.json()["applied"] == 0


def test_stage_requires_user_chosen_slot(ab_env):  # noqa: F811
    client = ab_env["client"]
    _seed_old(ab_env, "a", "s1", "https://d.example/rss")
    _seed_old(ab_env, "a", "s2", "https://d.example/rss")

    # 未指定时段 → 422（服务端不替用户挑）。
    missing = client.post(
        "/api/v1/backlog/wizard/stage",
        json={"feedUrl": "https://d.example/rss", "olderThanDays": 7,
              "targetSlotId": ""},
        headers=ab_env["a"],
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["type"] == "invalid_backlog_wizard"

    slot = client.post(
        "/api/v1/queue/slots", json={"name": "晚间"}, headers=ab_env["a"]
    ).json()
    staged = client.post(
        "/api/v1/backlog/wizard/stage",
        json={"feedUrl": "https://d.example/rss", "olderThanDays": 7,
              "targetSlotId": slot["id"]},
        headers=ab_env["a"],
    )
    assert staged.status_code == 200, staged.text
    body = staged.json()
    assert body["stagedCount"] == 2

    # 再 stage：两篇都已有 pending 归属 → skipped=2（如实计数）。
    again = client.post(
        "/api/v1/backlog/wizard/stage",
        json={"feedUrl": "https://d.example/rss", "olderThanDays": 7,
              "targetSlotId": slot["id"]},
        headers=ab_env["a"],
    )
    assert again.json()["stagedCount"] == 0
    assert again.json()["skippedAlreadyInSlot"] == 2

    # B 的向导看不到 A 的来源（预览为空）。
    b_preview = client.post(
        "/api/v1/backlog/wizard/preview",
        json={"olderThanDays": 7},
        headers=ab_env["b"],
    )
    assert b_preview.json()["groups"] == []


def test_range_validation(ab_env):  # noqa: F811
    client = ab_env["client"]
    bad = client.post(
        "/api/v1/backlog/wizard/preview",
        json={"olderThanDays": 3},
        headers=ab_env["a"],
    )
    # pydantic 边界（ge=7/le=365）先拦 → 422 invalid_request；
    # store 层 validate_days 是第二道（调用路径内一致 422）。
    assert bad.status_code == 422
    big = client.post(
        "/api/v1/backlog/wizard/preview",
        json={"olderThanDays": 366},
        headers=ab_env["a"],
    )
    assert big.status_code == 422
