"""NEW-343 敏感资料标记 — 后端真实阻止（摘要/对话/翻译分段/对照）
+ 原因说明 + A/B 隔离。（不配置 provider：被阻止发生在任何上游调用
之前；解除后任务不再被本守卫拦下）"""

import asyncio

import pytest

from new2xx_ab import ab_env, seed_entry  # noqa: F401 — pytest 夹具注册

BLOCKS_PATH = "/api/v1/me/ai-send-blocks"


def _ref_for(env, who: str, item_id: str) -> str:
    seed_entry(env, who, item_id, title="敏感文章")
    from lumirss.entryref import encode_entry_ref

    return encode_entry_ref(item_id)


def test_new343_put_get_list_and_validation(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = _ref_for(ab_env, "a", "n343-item-1")

    listed = client.get(BLOCKS_PATH, headers=ab_env["a"])
    assert listed.status_code == 200
    assert listed.json()["items"] == []
    assert "不经过 Lumi" in listed.json()["note"]

    marked = client.put(
        f"{BLOCKS_PATH}/{ref}",
        json={"reason": "含个人身份信息"},
        headers=ab_env["a"],
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["reason"] == "含个人身份信息"

    got = client.get(BLOCKS_PATH, headers=ab_env["a"]).json()["items"]
    assert len(got) == 1 and got[0]["entryRef"] == ref

    too_long = client.put(
        f"{BLOCKS_PATH}/{ref}", json={"reason": "x" * 201}, headers=ab_env["a"]
    )
    assert too_long.status_code == 422
    bad_ref = client.put(f"{BLOCKS_PATH}/not-a-ref", json={}, headers=ab_env["a"])
    assert bad_ref.status_code == 400


def test_new343_summary_task_blocked_at_backend(ab_env):  # noqa: F811
    """标记后 POST summary → 403 ai_send_blocked（附用户原因）——
    阻止发生在配额/provider 之前（无 provider 配置也稳定 403）。"""
    client = ab_env["client"]
    ref = _ref_for(ab_env, "a", "n343-item-2")
    client.put(
        f"{BLOCKS_PATH}/{ref}", json={"reason": "医疗记录"}, headers=ab_env["a"]
    )
    summary = client.post(f"/api/v1/entries/{ref}/summary", headers=ab_env["a"])
    assert summary.status_code == 403, summary.text
    error = summary.json()["error"]
    assert error["type"] == "ai_send_blocked"
    assert error["reason"] == "医疗记录"
    assert "不经过 Lumi" in error["note"]


def test_new343_conversation_and_translation_blocked(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = _ref_for(ab_env, "a", "n343-item-3")
    client.put(f"{BLOCKS_PATH}/{ref}", json={}, headers=ab_env["a"])

    conversation = client.post(
        f"/api/v1/entries/{ref}/conversation/messages",
        json={"question": "这篇讲了什么？"},
        headers=ab_env["a"],
    )
    assert conversation.status_code == 403
    assert conversation.json()["error"]["type"] == "ai_send_blocked"

    segments = client.post(
        f"/api/v1/entries/{ref}/translation/segments/generate",
        json={"blocks": [{"index": 0, "text": "第一段"}]},
        headers=ab_env["a"],
    )
    assert segments.status_code == 403
    assert segments.json()["error"]["type"] == "ai_send_blocked"


def test_new343_clear_unblocks_and_isolation(ab_env):  # noqa: F811
    """解除后不再被本守卫拦；A 的标记拦不住 B 的同一 ref（隔离）。"""
    client = ab_env["client"]
    item_id = "n343-item-4"
    seed_entry(ab_env, "a", item_id)
    seed_entry(ab_env, "b", item_id)
    from lumirss.entryref import encode_entry_ref

    ref = encode_entry_ref(item_id)
    client.put(f"{BLOCKS_PATH}/{ref}", json={"reason": "私密"}, headers=ab_env["a"])

    # B 未标记：不被拦（错误不再是 ai_send_blocked——无 provider 时是别的错误）。
    b_summary = client.post(f"/api/v1/entries/{ref}/summary", headers=ab_env["b"])
    assert b_summary.status_code != 403 or (
        b_summary.json()["error"]["type"] != "ai_send_blocked"
    )

    deleted = client.delete(f"{BLOCKS_PATH}/{ref}", headers=ab_env["a"])
    assert deleted.status_code == 200
    a_summary = client.post(f"/api/v1/entries/{ref}/summary", headers=ab_env["a"])
    assert a_summary.status_code != 403 or (
        a_summary.json()["error"]["type"] != "ai_send_blocked"
    )
    missing = client.delete(f"{BLOCKS_PATH}/{ref}", headers=ab_env["a"])
    assert missing.status_code == 404


def test_new343_store_pure_level():
    """模块层：默认原因兜底 + clean_reason 校验。"""
    from lumirss.new343_sensitive_marks import InvalidSensitiveMark, clean_reason

    assert clean_reason(None) == "含个人敏感信息，不发送至外部 AI。"
    assert clean_reason("  ") == "含个人敏感信息，不发送至外部 AI。"
    with pytest.raises(InvalidSensitiveMark):
        clean_reason(123)


def test_new343_denial_helper_direct():
    """denial 守卫：无标记 → None；有标记 → 错误体（真实库）。"""
    from lumirss.entryref import encode_entry_ref
    from lumirss.new343_sensitive_marks import (
        SensitiveMarkStore,
        ai_send_block_denial,
    )
    from lumirss.storage import Database

    async def run():
        db = Database("/tmp/n343-direct/lumi.sqlite")
        store = SensitiveMarkStore(db)
        ref = encode_entry_ref("n343-direct-1")
        assert await ai_send_block_denial(store, ref) is None
        await store.set_mark(ref, "合同草稿")
        denial = await ai_send_block_denial(store, ref)
        await store.clear_mark(ref)
        assert await store.get_mark(ref) is None
        return denial

    denial = asyncio.run(run())
    assert denial is not None
    assert denial["error"]["type"] == "ai_send_blocked"
    assert denial["error"]["reason"] == "合同草稿"
