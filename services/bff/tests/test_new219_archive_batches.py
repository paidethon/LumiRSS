"""NEW-219 文章批量归档 —— 条件预览、勾选归档、收据、撤销未被后续修改的部分。

验收：预览真实 COUNT + 有效排除（加星恒排除）；apply 只归档勾选的
refs（FreshRSS set_entry_state read=True + 投影镜像）；加星勾选 → 整批
409；收据可查；撤销恢复 read=0 且只动未被后续修改的（已读回/被动过星
的跳过并如实回报）；重复撤销 409；A/B 隔离。
"""

import asyncio

from new21x_isolation import seed_entry

run = asyncio.run


class FakeStateAdapter:
    """记录 set_entry_state 调用（FreshRSS 侧断言用）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool | None, bool | None]] = []

    async def set_entry_state(self, item_id, read=None, starred=None):
        self.calls.append((str(item_id), read, starred))


def _rows(client, item_ids: list[str]) -> dict[str, int]:
    placeholders = ",".join("?" for _ in item_ids)
    rows = run(
        client.app.state.db.fetch_all(
            f"SELECT item_id, read FROM search_entries WHERE item_id IN ({placeholders})",
            (*item_ids,),
        )
    )
    return {str(r["item_id"]): int(r["read"]) for r in rows}


def test_new219_preview_apply_receipt_and_partial_undo(client):
    seed_entry(client, "old1", title="旧文一", published_at="2026-01-01T00:00:00+00:00")
    seed_entry(client, "old2", title="旧文二", published_at="2026-02-01T00:00:00+00:00")
    seed_entry(client, "star", title="加星旧文", published_at="2026-03-01T00:00:00+00:00", starred=1)
    seed_entry(client, "fresh", title="新文", published_at="2026-09-20T00:00:00+00:00")

    # 预览：30 天前未读 → 候选 旧文一/旧文二/加星旧文，加星被服务端强制排除
    preview = client.post(
        "/api/v1/archive-batches/preview",
        json={"olderThanDays": 30},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["count"] == 2
    assert body["effectiveExclusions"] == ["starred"]
    assert {s["title"] for s in body["sample"]} == {"旧文一", "旧文二"}

    # apply：加星混入勾选 → 整批 409
    from lumirss.entryref import encode_entry_ref

    fake = FakeStateAdapter()
    client.app.state.freshrss_adapter = fake
    try:
        refused = client.post(
            "/api/v1/archive-batches",
            json={"refs": [s["ref"] for s in body["sample"]]
                  + [f"rss:{encode_entry_ref('star')}"]},
        )
        assert refused.status_code == 409
        assert refused.json()["error"]["type"] == "archive_batch_refused"
        assert fake.calls == []  # 拒绝发生在任何上游写之前

        # apply：只勾选 旧文一/旧文二
        refs = [s["ref"] for s in body["sample"] if s["title"].startswith("旧文")]
        applied = client.post("/api/v1/archive-batches", json={"refs": refs})
        assert applied.status_code == 200, applied.text
        receipt = applied.json()
        assert receipt["archived"] and len(receipt["archived"]) == 2
        assert fake.calls and all(c[1] is True for c in fake.calls)
        assert _rows(client, ["old1", "old2"]) == {"old1": 1, "old2": 1}

        # 收据：列表 + 单条
        listed = client.get("/api/v1/archive-batches").json()["items"]
        assert [r["batchId"] for r in listed] == [receipt["batchId"]]
        fetched = client.get(f"/api/v1/archive-batches/{receipt['batchId']}").json()
        assert fetched["archivedCount"] == 2
        assert set(fetched["snapshots"]) == set(receipt["archived"])

        # 撤销前的「后续修改」：把旧文二加星（模拟用户动过）
        from lumirss.entryref import decode_entry_ref

        old2_ref = next(
            r for r in refs if decode_entry_ref(r.split(":", 1)[1]) == "old2"
        )
        run(
            client.app.state.db.execute(
                "UPDATE search_entries SET starred = 1 WHERE item_id = 'old2'"
            )
        )
        undo = client.post(f"/api/v1/archive-batches/{receipt['batchId']}/undo")
        assert undo.status_code == 200, undo.text
        undone = undo.json()
        assert len(undone["restored"]) == 1  # 只有未被修改的旧文一被恢复
        assert {"ref": old2_ref, "reason": "modified_since"} in undone["skipped"]
        assert any(c[1] is False for c in fake.calls)
        assert _rows(client, ["old1", "old2"]) == {"old1": 0, "old2": 1}

        # 重复撤销 → 409；404；引用形状 422
        again = client.post(f"/api/v1/archive-batches/{receipt['batchId']}/undo")
        assert again.status_code == 409
        assert (
            client.post("/api/v1/archive-batches/no-such/undo").status_code
            == 404
        )
        bad_ref = client.post(
            "/api/v1/archive-batches", json={"refs": ["library:00000000-0000-4000-8000-000000000000"]}
        )
        assert bad_ref.status_code == 422
    finally:
        client.app.state.freshrss_adapter = None


def test_new219_per_user_isolation(monkeypatch, tmp_path):
    """per-user 库：B 的归档收据对 A 不可见，A 撤不掉 B 的归档批。"""
    import os

    from lumirss.accounts_store import AccountsStore
    from lumirss.storage import Database
    from lumirss.user_scope import user_context
    from new21x_isolation import build_two_user_client, isolated_auth_env

    isolated_auth_env(monkeypatch, tmp_path)
    for client, owner, member in build_two_user_client():
        # 找到 B 的 user id（控制库），再在 B 的 user context 里落投影行
        control = Database(os.environ["LUMIRSS_DB_PATH"])
        accounts = AccountsStore(control)
        users = run(accounts.list_users(limit=50))
        member_uid = next(u["id"] for u in users if u["username"] != "owner")
        with user_context(member_uid):
            seed_entry(
                client, "b-old", title="乙的旧文", published_at="2026-01-01T00:00:00+00:00"
            )
        fake = FakeStateAdapter()
        client.app.state.freshrss_adapter = fake
        try:
            preview = client.post(
                "/api/v1/archive-batches/preview",
                json={"olderThanDays": 1},
                headers=member,
            )
            assert preview.json()["count"] == 1, preview.text
            applied = client.post(
                "/api/v1/archive-batches",
                json={"refs": [preview.json()["sample"][0]["ref"]]},
                headers=member,
            )
            assert applied.status_code == 200, applied.text
            batch_id = applied.json()["batchId"]
            assert applied.json()["archived"]

            # A 看不到 B 的收据列表，也撤不掉 B 的批次
            assert (
                client.get(
                    "/api/v1/archive-batches", headers=owner
                ).json()["items"]
                == []
            )
            assert (
                client.get(
                    f"/api/v1/archive-batches/{batch_id}", headers=owner
                ).status_code
                == 404
            )
            assert (
                client.post(
                    f"/api/v1/archive-batches/{batch_id}/undo", headers=owner
                ).status_code
                == 404
            )
            # B 自己能看到收据并撤销
            assert [
                r["batchId"]
                for r in client.get(
                    "/api/v1/archive-batches", headers=member
                ).json()["items"]
            ] == [batch_id]
            assert (
                client.post(
                    f"/api/v1/archive-batches/{batch_id}/undo",
                    headers=member,
                ).status_code
                == 200
            )
        finally:
            client.app.state.freshrss_adapter = None
