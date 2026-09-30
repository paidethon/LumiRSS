"""FIX-225 任务取消不是只改数据库标签 —— 执行循环必须在取消后：

1. 停止尚未开始的可取消工作（不再发起调用）；
2. 不把成功结果覆盖提交到已取消的项上（不可中断区段的结果被丢弃并
   如实上报 ``inFlightCancelled``）；
3. 不把已取消的审批单/批次复活为 completed/executed。

红先行：取消动作落在第一项执行中（不可中断区段）时，基线实现继续
跑完剩余项、把取消项覆盖成 done、并把整单复活为 completed/executed。
"""

import asyncio
import tempfile

from lumirss.new275_batch_approvals import BatchApprovalStore
from lumirss.new375_quota_batch import (
    cancel_batch,
    create_draft,
    execute_batch,
    get_batch,
)
from lumirss.storage import Database

REFS = [
    f"tag:google.com,2005:reader/item/000000000000000{i}" for i in (1, 2, 3)
]

CHANGES = [
    {"userId": f"user-{i}", "clear": False, "caps": {"aiQuotaPerDay": 5}}
    for i in (1, 2, 3)
]


def _db() -> Database:
    return Database(f"{tempfile.mkdtemp(prefix='fix225-')}/lumi.sqlite")


def test_new275_cancel_during_execute_stops_worker_and_keeps_cancelled():
    """执行中整单取消：worker 停止、取消项不收成功结果、不复活 completed。"""
    ran: list[str] = []

    async def scenario():
        db = _db()
        store = BatchApprovalStore(db)
        approval = await store.create("summary", REFS, 3)
        approval_id = approval["id"]
        await store.approve(approval_id)

        async def run_item(entry_ref: str, kind: str) -> tuple[str, str | None]:
            ran.append(entry_ref)
            if len(ran) == 1:
                # 第 1 项的不可中断区段内，整单取消并发落下（真实
                # 部署里是另一个请求在 run_item 的 await 间隙写入）。
                await store.cancel(approval_id)
            return ("done", None)

        return await store.execute(approval_id, run_item)

    result = asyncio.run(scenario())

    # worker 停止可取消工作：只有第 1 项真正发起过调用
    assert len(ran) == 1, f"取消后仍执行了 {len(ran)} 项"
    # 不可中断区段的结果不覆盖取消：明确状态 + 所有项保持 cancelled
    assert result["execution"]["inFlightCancelled"] == 1
    assert all(i["status"] == "cancelled" for i in result["items"])
    # 取消后的审批单不被执行循环复活为 completed
    assert result["status"] == "cancelled"


def test_new275_cancel_item_mid_flight_discards_result():
    """单项取消落在该项执行中：结果被丢弃（保持 cancelled），后续项照常。"""
    ran: list[str] = []

    async def scenario():
        db = _db()
        store = BatchApprovalStore(db)
        approval = await store.create("summary", REFS, 3)
        approval_id = approval["id"]
        await store.approve(approval_id)
        items = {i["entryRef"]: i["id"] for i in approval["items"]}

        async def run_item(entry_ref: str, kind: str) -> tuple[str, str | None]:
            ran.append(entry_ref)
            if entry_ref == REFS[0]:
                await store.cancel(approval_id, items[entry_ref])
            return ("done", None)

        return await store.execute(approval_id, run_item)

    result = asyncio.run(scenario())

    assert ran == [REFS[0], REFS[1], REFS[2]]  # 其余项照常
    first = next(i for i in result["items"] if i["entryRef"] == REFS[0])
    assert first["status"] == "cancelled"  # 结果被丢弃，不覆盖成 done
    assert result["execution"]["inFlightCancelled"] == 1
    assert result["status"] == "completed"  # 剩余项完成 → 整单完成


def test_new375_cancelled_batch_not_resurrected_to_executed(monkeypatch):
    """取消落在逐账户执行中：worker 停止后续账户，最终状态保持 cancelled
    （已执行账户的结果行照常落账，诚实呈现）。"""

    ran: list[str] = []

    async def scenario():
        control_db = _db()
        batch = await create_draft(control_db, changes=CHANGES, by="admin-1")
        batch_id = batch["batchId"]

        from lumirss import accounts_store, new375_quota_batch

        real_quota_store = new375_quota_batch.UserQuotaStore

        class FakeAccounts:
            def __init__(self, _db) -> None:
                pass

            async def get_user(self, user_id: str):
                return {"id": user_id, "username": user_id}

        class SlowQuotaStore:
            """包装真实 store：第 1 个账户 set_caps 的 await 间隙里落下
            取消（模拟并发 admin 请求的写入窗口）。"""

            def __init__(self, _db) -> None:
                self._inner = real_quota_store(_db)

            async def caps_for(self, user_id: str):
                return await self._inner.caps_for(user_id)

            async def clear_caps(self, **kwargs):
                return await self._inner.clear_caps(**kwargs)

            async def set_caps(self, **kwargs):
                ran.append(kwargs["user_id"])
                if len(ran) == 1:
                    await cancel_batch(control_db, batch_id)
                return await self._inner.set_caps(**kwargs)

        monkeypatch.setattr(accounts_store, "AccountsStore", FakeAccounts)
        monkeypatch.setattr(new375_quota_batch, "UserQuotaStore", SlowQuotaStore)

        result = await execute_batch(
            object(), control_db, batch_id=batch_id, by="admin-1"
        )
        final = await get_batch(control_db, batch_id)
        return result, final

    result, final = asyncio.run(scenario())

    # worker 停止可取消工作：只有第 1 个账户被执行
    assert len(ran) == 1, f"取消后仍执行了 {len(ran)} 个账户"
    # 取消不被复活为 executed
    assert result["status"] == "cancelled"
    assert final is not None and final["status"] == "cancelled"
