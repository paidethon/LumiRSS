"""N162 批量写入预演聚合卡 + N163 研究模式预设测试。

N162：
- 批量形态（itemRefs 列表）的 add_tag 审批，preview 返回一张聚合卡：
  {objectCount, perObjectDeltas ≤10 样本, uncertainCount}；
- 任一对象不确定（幂等重复）→ uncertainCount > 0 且整批 uncertain 提示；
- 单次批准即覆盖整批（args_hash 绑定批量 args，执行逐对象落地）。

N163：
- POST /agent/presets/research：readonly + read-tool 白名单 + 回合上限
  一次落库（scope 保留）；之后写工具 → 403 readonly_mode。
"""

import asyncio

from lumirss.agent_store import AgentStore
from lumirss.itemref import new_library_uuid
from lumirss.tags import TagStore


def run(coroutine):
    return asyncio.run(coroutine)


REF_A = f"library:{new_library_uuid()}"
REF_B = f"library:{new_library_uuid()}"
REF_C = f"library:{new_library_uuid()}"


async def _seed(client) -> None:
    from lumirss.search_library import LibrarySearchWriter

    writer = LibrarySearchWriter(client.app.state.db)
    for ref, title in (
        (REF_A, "文章甲"),
        (REF_B, "文章乙"),
        (REF_C, "文章丙"),
    ):
        await writer.upsert(ref=ref, kind="clip", title=title, body="正文。", url=None)


def _store(client) -> AgentStore:
    return AgentStore(client.app.state.db)





def test_batch_preview_aggregated_and_uncertain_marks_batch(client):
    run(_seed(client))
    store = _store(client)
    # REF_B 先打上标签 → 批量预演时该对象「幂等重复」= 不确定项。
    run(TagStore(client.app.state.db).attach(REF_B, "重点", origin="manual"))

    thread = run(store.create_thread())
    approval = run(
        store.create_approval(
            thread["id"],
            "call-batch-1",
            "add_tag",
            {"itemRefs": [REF_A, REF_B, REF_C], "name": "重点"},
        )
    )
    response = client.post(
        f"/api/v1/agent/threads/{thread['id']}/approvals/{approval['approvalId']}/preview"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    batch = body["batch"]
    assert batch is not None
    assert batch["objectCount"] == 3
    assert batch["uncertainCount"] == 1
    assert len(batch["perObjectDeltas"]) == 3
    refs = {delta["ref"] for delta in batch["perObjectDeltas"]}
    assert refs == {REF_A, REF_B, REF_C}
    # 不确定对象的变化列表为空；其余对象给出 tag delta。
    by_ref = {d["ref"]: d for d in batch["perObjectDeltas"]}
    assert by_ref[REF_B]["changes"] == []
    assert by_ref[REF_A]["changes"] == [{"field": "tag", "from": None, "to": "重点"}]
    # 整批 uncertain 提示（对象级不确定性提升到批量卡）。
    assert any("幂等" in u for u in body["uncertain"])
    # 单对象形态不产生批量卡。
    single = run(
        store.create_approval(
            thread["id"], "call-single-1", "add_tag", {"itemRef": REF_A, "name": "重点"}
        )
    )
    response = client.post(
        f"/api/v1/agent/threads/{thread['id']}/approvals/{single['approvalId']}/preview"
    )
    assert response.status_code == 200
    assert response.json()["batch"] is None

    # 单次批准覆盖整批：以批准行携带的批量 args 直接调用注册表执行器
    # （apply_approval 的同一入口 invoke_write），验证整批一次性落地。
    from lumirss.agent_tools import build_registry

    db = client.app.state.db
    registry = build_registry(tags=TagStore(db), workspaces=None, library=None, rag=None, db=db, rss_search=None, library_search=None)
    result = run(registry.invoke_write("add_tag", approval["args"]))
    assert result["objectCount"] == 3
    for ref in (REF_A, REF_B, REF_C):
        tagged = run(TagStore(client.app.state.db).tags_for_item(ref))
        assert "重点" in {t["name"] for t in tagged}  # REF_B 幂等重复不炸


def test_batch_preview_samples_capped_at_ten(client):
    run(_seed(client))
    store = _store(client)
    refs = [f"library:{new_library_uuid()}" for _ in range(14)]
    thread = run(store.create_thread())
    approval = run(
        store.create_approval(
            thread["id"],
            "call-batch-2",
            "add_tag",
            {"itemRefs": refs, "name": "批量"},
        )
    )
    response = client.post(
        f"/api/v1/agent/threads/{thread['id']}/approvals/{approval['approvalId']}/preview"
    )
    assert response.status_code == 200, response.text
    batch = response.json()["batch"]
    assert batch["objectCount"] == 14
    assert len(batch["perObjectDeltas"]) == 10
    assert batch["perObjectTruncated"] == 4
    assert batch["uncertainCount"] == 0


def test_research_preset_blocks_writes(client, monkeypatch):
    run(_seed(client))
    store = _store(client)
    thread = run(store.create_thread())

    response = client.post(
        "/api/v1/agent/presets/research", json={"threadId": thread["id"]}
    )
    assert response.status_code == 200, response.text
    settings = response.json()
    assert settings["toolPolicy"]["mode"] == "readonly"
    assert "search" in settings["toolPolicy"]["allowedTools"]
    assert "add_tag" not in settings["toolPolicy"]["allowedTools"]
    assert settings["budget"]["maxTurns"] >= 1

    # 会话内评估：写工具在 readonly 模式下被拒（readonly_mode）。
    from lumirss.agent_session import evaluate_policy

    policy = settings["toolPolicy"]
    assert evaluate_policy(policy, "add_tag", is_write=True) == "readonly_mode"
    assert evaluate_policy(policy, "search", is_write=False) is None

    # 未知会话 → 404。
    missing = client.post(
        "/api/v1/agent/presets/research", json={"threadId": "nope"}
    )
    assert missing.status_code == 404
