"""N156 资料冲突对照测试 —— 纯词法（零模型）的重叠句差异检测。

- fixture 冲突资料：两个 ref 各含高重叠但数字不同的句子 → number；
  日期不同的句子 → date；词汇差异 → other；
- 检出冲突并附证据定位（blockIndex）；
- 零模型调用（provider 工厂被注入即爆炸——断言端点从不触碰）；
- refs 范围：不存在/他人投影 → 422 citation_invalid；refs ≤5。
"""

import asyncio

import pytest

from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.qa_conflicts import detect_conflicts, split_sentences


def run(coro):
    return asyncio.run(coro)


def _seed_entries(rows: list[tuple[str, str]]) -> list[str]:
    """search_entries 直接播种；返回 rss: refs。"""
    db = app.state.db

    async def _seed():
        await db.migrate()
        for item_id, text in rows:
            await db.execute(
                "INSERT OR REPLACE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, '源', ?, '', '', ?, '2026-09-01T00:00:00+00:00', 0, 0, 0)",
                (
                    item_id,
                    encode_entry_ref(item_id),
                    f"https://feed.example/{item_id}",
                    f"条目{item_id}",
                    text,
                ),
            )

    run(_seed())
    # RAG 资料命名空间：rss 条目用裸 entry_ref（与 rag_chunks.ref、
    # /rag/ask refs 同一口径）。
    return [encode_entry_ref(item_id) for item_id, _text in rows]


@pytest.fixture()
def conflicting_refs(client):
    return _seed_entries(
        [
            (
                "8001",
                "这家公司在年度大会上正式宣布完成新一轮融资 3,500 万美元。"
                "研发团队规模没有变化。"
                "筹备多时的发布会定于 2026-03-01 在北京亦庄举行。"
                "产品将于本月正式发布。",
            ),
            (
                "8002",
                "这家公司在年度大会上正式宣布完成新一轮融资 5,000 万美元。"
                "研发团队规模没有变化。"
                "筹备多时的发布会定于 2026-04-15 在北京亦庄举行。"
                "产品将于本月正式发布。",
            ),
        ]
    )


def test_detect_conflicts_number_and_date(client, conflicting_refs):
    ref_a, ref_b = conflicting_refs
    response = client.post(
        "/api/v1/qa/conflicts", json={"refs": [ref_a, ref_b]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["basis"] == "lexical"
    assert body["pairsCompared"] == 1
    kinds = {c["diffKind"] for c in body["conflicts"]}
    assert "number" in kinds  # 3,500 vs 5,000
    assert "date" in kinds  # 2026-03-01 vs 2026-04-15
    for conflict in body["conflicts"]:
        assert conflict["aRef"] == ref_a
        assert conflict["bRef"] == ref_b
        assert conflict["aQuote"] and conflict["bQuote"]
        assert conflict["overlap"] >= 0.5
        assert conflict["aEvidence"]["ref"] == ref_a
        assert conflict["bEvidence"]["ref"] == ref_b


def test_conflicts_involve_no_model_calls(client, conflicting_refs, monkeypatch):
    """provider 工厂一旦被触碰即爆炸——本比对必须是纯词法通道。"""

    def _explode(*args, **kwargs):
        raise AssertionError("N156 对照通道不得调用 AI provider")

    import lumirss.deps as deps

    monkeypatch.setattr(deps, "_provider_factory_for", _explode)
    ref_a, ref_b = conflicting_refs
    response = client.post(
        "/api/v1/qa/conflicts", json={"refs": [ref_a, ref_b]}
    )
    assert response.status_code == 200


def test_conflicts_refs_scoped_and_bounded(client, conflicting_refs):
    ref_a, _ref_b = conflicting_refs
    unknown = encode_entry_ref("9999")
    missing = client.post(
        "/api/v1/qa/conflicts", json={"refs": [ref_a, unknown]}
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["type"] == "citation_invalid"
    too_many = client.post(
        "/api/v1/qa/conflicts",
        json={"refs": [ref_a, unknown, "a1", "a2", "a3", "a4"]},
    )
    assert too_many.status_code == 422


def test_detect_conflicts_unit_level():
    """单元口径：identical 句不成冲突；词汇差异 → other。"""
    assert split_sentences("第一句。第二句！第三句") == [
        "第一句。",
        "第二句！",
        "第三句",
    ]
    conflicts = detect_conflicts(
        {
            "a": "营收为 100 万。",
            "b": "营收为 200 万。",
            "c": "完全不同的文本内容，与前面没有重叠。",
        }
    )
    kinds = [c["diffKind"] for c in conflicts]
    assert "number" in kinds
    # 短句（无重叠）不产生冲突对。
    assert all(
        {c["aRef"], c["bRef"]} == {"a", "b"} for c in conflicts
    )


# -- FIX-316：引用块位来自旧正文版本 → 诚实缺位，绝不指向无关段落 ----------


def test_stale_index_block_position_is_not_served_as_current(client, conflicting_refs):
    """分块的 content_hash ≠ 当前投影正文 hash（正文已改、索引未重建）
    时，冲突证据块定位必须诚实缺位（blockIndex=None），绝不把旧正文
    版本的 rag_chunks.ord 当作当前文本的块位返回；仍新鲜的 ref 保持
    正常块位。"""
    from lumirss.main import app
    from lumirss.rag import RagService

    db = app.state.db
    service = RagService(db, db_path=db.path)

    async def _fake_embed(texts):
        vectors = []
        for text in texts:
            vector = [0.0] * 512
            vector[len(text) % 512] = 1.0
            vectors.append(vector)
        return vectors

    service._embedder.embed = _fake_embed  # noqa: SLF001 — 测试缝
    app.state.rag_service = service
    try:
        ref_a, ref_b = conflicting_refs

        async def _index_and_mutate():
            await db.migrate()
            await service.index_refs([ref_a, ref_b])
            # A 正文变更（金额改写）但索引未重建 → A 的分块整体过期。
            await db.execute(
                "UPDATE search_entries SET content_text = ? WHERE entry_ref = ?",
                (
                    "这家公司在年度大会上正式宣布完成新一轮融资 6,000 万美元。"
                    "研发团队规模没有变化。"
                    "筹备多时的发布会定于 2027-06-01 在上海临港举行。"
                    "产品将于本月正式发布。",
                    ref_a,
                ),
            )

        run(_index_and_mutate())

        response = client.post(
            "/api/v1/qa/conflicts", json={"refs": [ref_a, ref_b]}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["conflicts"], "过期分块仍是索引文本，冲突应被检出"
        evidence_by_ref = {}
        for conflict in body["conflicts"]:
            evidence_by_ref[conflict["aRef"]] = conflict["aEvidence"]
            evidence_by_ref[conflict["bRef"]] = conflict["bEvidence"]
        # 过期 ref：旧块位绝不外带（FIX-316）。
        assert evidence_by_ref[ref_a]["blockIndex"] is None
        # 仍新鲜的 ref：正常块位保留。
        assert evidence_by_ref[ref_b]["blockIndex"] is not None
    finally:
        app.state.rag_service = None
        service.close()
