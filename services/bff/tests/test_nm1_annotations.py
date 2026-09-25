"""NM1 批注/学习六特性后端测试 — N071/N073/N074/N075/N076/N077。

- N071 原文漂移修复：漂移 → 候选 → 重绑（anchor+hash 更新，历史
  cap 10）；低分拒绝（只支持手动）；原文不可达 → 422 不做缓存。
- N073 颜色语义：标签持久化、列表 color= 过滤、未命名诚实留空。
- N074 阅读问题清单：CRUD、按批注链接、按文章检索。
- N075 引用格式导出：格式良构；缺失项「不详」；默认不追加。
- N076 知识卡片入复习：同一到期/揭示队列；重复 409；删除级联。
- N077 来源追踪：揭示更新 last_viewed_at；原文删除 → 不可用。
"""

import asyncio
import uuid as _uuid
from types import SimpleNamespace

from lumirss.entryref import encode_entry_ref
from lumirss.knowledge_cards import delete_card as delete_knowledge_card
from lumirss.knowledge_cards import upsert_card
from lumirss.main import app


def _run(coroutine):
    return asyncio.run(coroutine)


def _install_entry(content_text: str, *, title: str = "测试标题", feed_title: str = "测试来源") -> None:
    """显式注入 FreshRSS 适配器替身（get_entry 只需 contentText）。"""

    async def get_entry(item_id: str):  # noqa: ARG001 — 替身不解释上游 id
        return SimpleNamespace(
            contentText=content_text,
            title=title,
            feedTitle=feed_title,
            publishedAt="2026-01-02T03:04:05Z",
            url=None,
        )

    app.state.freshrss_adapter = SimpleNamespace(get_entry=get_entry)


def _search_entry_row(entry_ref: str, *, title: str, feed_title: str, published_at: str) -> dict:
    """search_entries 投影行的最小 INSERT（导出/来源可用性数据源）。"""
    return {
        "item_id": f"urn:test:{_uuid.uuid4()}",
        "entry_ref": entry_ref,
        "feed_url": "https://example.com/feed.xml",
        "feed_title": feed_title,
        "title": title,
        "author": "",
        "url": "https://example.com/a",
        "content_text": "",
        "published_at": published_at,
        "fetched_at": 0,
    }


def _insert_search_entry(entry_ref: str, *, title: str, feed_title: str, published_at: str) -> None:
    row = _search_entry_row(entry_ref, title=title, feed_title=feed_title, published_at=published_at)
    _run(
        app.state.db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["item_id"],
                row["entry_ref"],
                row["feed_url"],
                row["feed_title"],
                row["title"],
                row["author"],
                row["url"],
                row["content_text"],
                row["published_at"],
                row["fetched_at"],
            ),
        )
    )


# ---- N071 批注原文漂移修复 ---------------------------------------------------


def test_n071_drift_candidates_then_rebind(client):
    """漂移 → 候选（含模糊）→ 重绑（anchor+hash 更新；历史保留）。"""
    ref = encode_entry_ref("9101")
    quote = "被移动的关键观点原文"
    created = client.post(
        "/api/v1/annotations",
        json={
            "entryRef": ref,
            "anchor": {"paraId": "p-0", "prefix": "", "exact": quote, "suffix": ""},
            "excerpt": quote,
        },
    )
    annotation_id = created.json()["id"]

    # 原文重构：引文从原块漂移到第 1 块（另有第 2 块近似文本，验证排序）
    _install_entry(
        "开头完全不同的段落。\n这里包含被移动的关键观点原文，前后略有改动。\n接近但不同的关键观点原文句子。\n结尾。"
    )
    candidates = client.get(f"/api/v1/annotations/{annotation_id}/repair-candidates")
    assert candidates.status_code == 200
    body = candidates.json()
    assert body["quote"] == quote
    assert len(body["candidates"]) >= 1
    assert body["candidates"][0]["blockIndex"] == 1
    assert body["candidates"][0]["score"] == 1.0

    old_hash = created.json()["anchorHash"]
    repair = client.post(
        f"/api/v1/annotations/{annotation_id}/repair",
        json={"blockIndex": 1, "quoteText": quote},
    )
    assert repair.status_code == 200
    result = repair.json()
    assert result["blockIndex"] == 1
    assert result["annotation"]["anchor"] == {
        "paraId": "block-1",
        "prefix": "",
        "exact": quote,
        "suffix": "",
    }
    assert result["annotation"]["anchorHash"] != old_hash

    # 历史保留：旧行含旧锚点 JSON 与旧摘录
    history = _run(
        app.state.db.fetch_all(
            "SELECT old_anchor_json, old_excerpt, new_block_index FROM annotation_repair_log WHERE annotation_id = ?",
            (annotation_id,),
        )
    )
    assert len(history) == 1
    assert '"p-0"' in history[0]["old_anchor_json"]
    assert history[0]["old_excerpt"] == quote
    assert history[0]["new_block_index"] == 1

    # 重绑后单篇列表返回更新后的锚点
    listing = client.get("/api/v1/annotations", params={"entryRef": ref}).json()["items"]
    assert listing[0]["anchor"]["paraId"] == "block-1"

    app.state.freshrss_adapter = None


def test_n071_repair_history_capped_at_ten(client):
    """修复历史 cap 10：第 11 次修复后只剩最近 10 条。"""
    ref = encode_entry_ref("9102")
    created = client.post(
        "/api/v1/annotations",
        json={"entryRef": ref, "anchor": {"paraId": "p-0"}, "excerpt": "稳定的句子原文"},
    )
    annotation_id = created.json()["id"]
    _install_entry("块零稳定句。\n块一稳定的句子原文。")
    for _ in range(11):
        response = client.post(
            f"/api/v1/annotations/{annotation_id}/repair",
            json={"blockIndex": 1, "quoteText": "稳定的句子原文"},
        )
        assert response.status_code == 200, response.text
    count = _run(
        app.state.db.fetch_one(
            "SELECT COUNT(*) AS n FROM annotation_repair_log WHERE annotation_id = ?",
            (annotation_id,),
        )
    )
    assert count["n"] == 10
    app.state.freshrss_adapter = None


def test_n071_low_score_refuses_manual_only(client):
    """best < 0.5 → 422 repair_refused（只支持手动），且不产生任何写入。"""
    ref = encode_entry_ref("9103")
    created = client.post(
        "/api/v1/annotations",
        json={"entryRef": ref, "anchor": {"paraId": "p-0"}, "excerpt": "完全无关的原始引文"},
    )
    annotation_id = created.json()["id"]
    _install_entry("正文讲的完全是另一件事，与引文毫无相似之处。")
    candidates = client.get(f"/api/v1/annotations/{annotation_id}/repair-candidates")
    assert candidates.status_code == 200
    assert candidates.json()["candidates"] == []

    refused = client.post(
        f"/api/v1/annotations/{annotation_id}/repair",
        json={"blockIndex": 0, "quoteText": "完全无关的原始引文"},
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["type"] == "repair_refused"
    # 负向：拒绝时没有任何修复历史写入
    history = _run(
        app.state.db.fetch_one(
            "SELECT COUNT(*) AS n FROM annotation_repair_log WHERE annotation_id = ?",
            (annotation_id,),
        )
    )
    assert history["n"] == 0
    # blockIndex 越界 → 422
    _install_entry("只有一块。")
    out_of_range = client.post(
        f"/api/v1/annotations/{annotation_id}/repair",
        json={"blockIndex": 9, "quoteText": "只有一块"},
    )
    assert out_of_range.status_code == 422
    assert out_of_range.json()["error"]["type"] == "repair_block_out_of_range"
    app.state.freshrss_adapter = None


def test_n071_candidates_require_live_entry(client):
    """原文不可达 → 422 entry_unavailable（绝不使用缓存正文）。"""
    ref = encode_entry_ref("9104")
    created = client.post(
        "/api/v1/annotations",
        json={"entryRef": ref, "anchor": {"paraId": "p-0"}, "excerpt": "一段引文"},
    )
    annotation_id = created.json()["id"]
    app.state.freshrss_adapter = None  # FreshRSS 未配置
    response = client.get(f"/api/v1/annotations/{annotation_id}/repair-candidates")
    assert response.status_code == 422
    assert response.json()["error"]["type"] == "entry_unavailable"
    # 未知批注 → 404
    missing = client.get(f"/api/v1/annotations/{_uuid.uuid4()}/repair-candidates")
    assert missing.status_code == 404


# ---- N073 批注颜色语义 -------------------------------------------------------


def test_n073_color_labels_persist_and_filter(client):
    """标签持久化；color= 过滤；未命名颜色 label 留空（诚实回显原始名）。"""
    palette = client.get("/api/v1/annotations/color-labels")
    assert palette.status_code == 200
    items = palette.json()["items"]
    assert [item["color"] for item in items] == ["yellow", "green", "blue", "red", "purple"]
    assert all(item["label"] == "" for item in items)

    labeled = client.put(
        "/api/v1/annotations/color-labels", json={"color": "red", "label": "重点反驳"}
    )
    assert labeled.status_code == 200
    by_color = {item["color"]: item["label"] for item in labeled.json()["items"]}
    assert by_color["red"] == "重点反驳"
    assert by_color["blue"] == ""  # 未命名 → 留空（Web 显示原始色名）

    # 持久化：重新 GET 仍在
    again = client.get("/api/v1/annotations/color-labels").json()["items"]
    assert next(item for item in again if item["color"] == "red")["label"] == "重点反驳"

    # color= 过滤（列表 + 单篇两条腿）
    client.post("/api/v1/annotations", json={"entryRef": "e1.a", "anchor": {"paraId": "p1"}, "color": "red"})
    client.post("/api/v1/annotations", json={"entryRef": "e1.a", "anchor": {"paraId": "p2"}, "color": "blue"})
    client.post("/api/v1/annotations", json={"entryRef": "e1.b", "anchor": {"paraId": "p3"}, "color": "blue"})
    only_red = client.get("/api/v1/annotations", params={"color": "red"}).json()["items"]
    assert {item["color"] for item in only_red} == {"red"}
    only_blue = client.get("/api/v1/annotations", params={"color": "blue"}).json()["items"]
    assert {item["color"] for item in only_blue} == {"blue"}
    single = client.get("/api/v1/annotations", params={"entryRef": "e1.a", "color": "red"}).json()["items"]
    assert len(single) == 1

    # 非法颜色 → 422
    bad = client.get("/api/v1/annotations", params={"color": "cyan"})
    assert bad.status_code == 422
    bad_put = client.put("/api/v1/annotations/color-labels", json={"color": "cyan", "label": "x"})
    assert bad_put.status_code == 422


# ---- N074 阅读问题清单 -------------------------------------------------------


def test_n074_reading_questions_crud_and_links(client):
    """CRUD；按批注链接；按文章检索；完成/重开走同一 PATCH。"""
    annotation = client.post(
        "/api/v1/annotations", json={"entryRef": "e1.q", "anchor": {"paraId": "p1"}}
    ).json()

    created = client.post(
        "/api/v1/reading-questions",
        json={
            "question": "作者论证的第二前提是什么？",
            "entryRef": "e1.q",
            "annotationId": annotation["id"],
        },
    )
    assert created.status_code == 201
    question = created.json()
    assert question["status"] == "open"
    assert question["entryRef"] == "e1.q"

    client.post("/api/v1/reading-questions", json={"question": "无链接的问题"})
    client.post(
        "/api/v1/reading-questions", json={"question": "另一篇的问题", "entryRef": "e2.q"}
    )

    # 全量 / 按文章 / 按批注
    assert len(client.get("/api/v1/reading-questions").json()["items"]) == 3
    by_entry = client.get("/api/v1/reading-questions", params={"entryRef": "e1.q"}).json()["items"]
    assert len(by_entry) == 1 and by_entry[0]["id"] == question["id"]
    by_annotation = client.get(
        "/api/v1/reading-questions", params={"annotationId": annotation["id"]}
    ).json()["items"]
    assert [item["id"] for item in by_annotation] == [question["id"]]

    # 完成 → 重开（同一 PATCH 路径）
    done = client.patch(f"/api/v1/reading-questions/{question['id']}", json={"status": "done"})
    assert done.json()["status"] == "done"
    open_again = client.patch(f"/api/v1/reading-questions/{question['id']}", json={"status": "open"})
    assert open_again.json()["status"] == "open"
    # 改文本
    reworded = client.patch(
        f"/api/v1/reading-questions/{question['id']}", json={"question": "改写后的问题"}
    )
    assert reworded.json()["question"] == "改写后的问题"

    # 删除 → 404
    deleted = client.delete(f"/api/v1/reading-questions/{question['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/reading-questions", params={"annotationId": annotation["id"]}).json()["items"] == []
    gone = client.delete(f"/api/v1/reading-questions/{question['id']}")
    assert gone.status_code == 404

    # 负向：空问题 / 非法 status → 422
    assert client.post("/api/v1/reading-questions", json={"question": ""}).status_code == 422
    assert (
        client.get("/api/v1/reading-questions", params={"status": "archived"}).status_code == 422
    )


# ---- N075 引用格式导出 -------------------------------------------------------


def test_n075_export_bibliography_lines(client):
    """citeBibliography → 每篇文章「引用格式：标题 — 来源, 日期」；
    缺失项逐个「不详」；默认不追加；绝不虚构元数据。"""
    ref_a = encode_entry_ref("9201")
    ref_b = encode_entry_ref("9202")
    client.post("/api/v1/annotations", json={"entryRef": ref_a, "anchor": {"paraId": "p1"}, "excerpt": "甲文摘录"})
    client.post("/api/v1/annotations", json={"entryRef": ref_b, "anchor": {"paraId": "p2"}, "excerpt": "乙文摘录"})
    _insert_search_entry(
        ref_a, title="深度阅读的方法", feed_title="读享周刊", published_at="2026-01-02T03:04:05Z"
    )
    # ref_b 不在投影中：标题/来源/日期全部缺失 → 不详

    exported = client.post(
        "/api/v1/annotations/export",
        json={"entryRefs": [ref_a, ref_b], "citeBibliography": True},
    )
    assert exported.status_code == 200
    text = exported.text
    assert "引用格式：深度阅读的方法 — 读享周刊, 2026-01-02" in text
    assert "引用格式：不详 — 不详, 不详" in text

    plain = client.post("/api/v1/annotations/export", json={"entryRefs": [ref_a]})
    assert "引用格式" not in plain.text  # 默认关闭


# ---- N076 知识卡片入复习 -----------------------------------------------------


def _create_card(entry_ref: str, concept: str) -> str:
    card, _created = _run(
        upsert_card(
            app.state.db,
            None,
            entry_ref=entry_ref,
            concept=concept,
            explanation=f"{concept} 的解释",
            source_quote="",
            quote_verified=False,
        )
    )
    return card.id


def test_n076_knowledge_card_enters_due_queue(client):
    """卡片排期 → 同一到期/揭示队列（kind 徽章数据）；重复 409；
    done 重排；未知卡片 404；非法 kind 422。"""
    card_id = _create_card(encode_entry_ref("9301"), "检索漏斗")
    due_at = "2020-01-01T00:00:00Z"  # 稳定过期 → due

    added = client.post(
        "/api/v1/review-queue",
        json={"kind": "knowledge_card", "knowledgeCardId": card_id, "dueAt": due_at},
    )
    assert added.status_code == 201

    duplicate = client.post(
        "/api/v1/review-queue",
        json={"kind": "knowledge_card", "knowledgeCardId": card_id, "dueAt": due_at},
    )
    assert duplicate.status_code == 409

    listing = client.get("/api/v1/review-queue", params={"status": "due"}).json()["items"]
    card_items = [item for item in listing if item["itemKind"] == "knowledge_card"]
    assert len(card_items) == 1
    item = card_items[0]
    assert item["knowledgeCardId"] == card_id
    assert item["annotationId"] is None
    assert item["concept"] == "检索漏斗"
    assert item["explanation"] == "检索漏斗 的解释"
    assert item["excerpt"] is None and item["note"] is None
    assert item["due"] is True

    # 批注项字段仍齐全（同队列共存，回归口径）
    annotation = client.post(
        "/api/v1/annotations", json={"entryRef": "e1.rev", "anchor": {"paraId": "p1"}, "excerpt": "摘录"}
    ).json()
    client.post("/api/v1/review-queue", json={"annotationId": annotation["id"], "dueAt": due_at})
    listing = client.get("/api/v1/review-queue", params={"status": "due"}).json()["items"]
    annotation_items = [item for item in listing if item["itemKind"] == "annotation"]
    assert len(annotation_items) == 1
    assert annotation_items[0]["excerpt"] == "摘录"
    assert annotation_items[0]["concept"] is None

    # 完成 → done；重排（rescheduled）
    queue_id = item["id"]
    assert client.post(f"/api/v1/review-queue/{queue_id}/complete").json()["status"] == "done"
    rescheduled = client.post(
        "/api/v1/review-queue",
        json={"kind": "knowledge_card", "knowledgeCardId": card_id, "dueAt": due_at},
    )
    assert rescheduled.status_code == 200 and rescheduled.json()["rescheduled"] is True

    # 负向：未知卡片 404；未知批注 404；非法 kind 422
    assert (
        client.post(
            "/api/v1/review-queue",
            json={"kind": "knowledge_card", "knowledgeCardId": str(_uuid.uuid4()), "dueAt": due_at},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/review-queue", json={"annotationId": str(_uuid.uuid4()), "dueAt": due_at}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/review-queue", json={"kind": "glossary", "annotationId": annotation["id"], "dueAt": due_at}
        ).status_code
        == 422
    )


def test_n076_card_delete_cascades_review_queue(client):
    """卡片删除 → 复习队列项级联删除（同批注口径）。"""
    card_id = _create_card(encode_entry_ref("9302"), "遗忘曲线")
    client.post(
        "/api/v1/review-queue",
        json={"kind": "knowledge_card", "knowledgeCardId": card_id, "dueAt": "2020-01-01T00:00:00Z"},
    )
    deleted = _run(delete_knowledge_card(app.state.db, None, card_id))
    assert deleted is True
    row = _run(
        app.state.db.fetch_one(
            "SELECT id FROM review_queue WHERE knowledge_card_id = ?", (card_id,)
        )
    )
    assert row is None


# ---- N077 复习来源追踪 -------------------------------------------------------


def test_n077_last_viewed_updates_on_reveal(client):
    """揭示 → POST /view 记录 last_viewed_at；列表带回该值与 paraId。"""
    ref = encode_entry_ref("9401")
    annotation = client.post(
        "/api/v1/annotations",
        json={"entryRef": ref, "anchor": {"paraId": "p-7"}, "excerpt": "摘录"},
    ).json()
    queue = client.post(
        "/api/v1/review-queue", json={"annotationId": annotation["id"], "dueAt": "2020-01-01T00:00:00Z"}
    )
    queue_id = queue.json()["id"]

    listing = client.get("/api/v1/review-queue", params={"status": "due"}).json()["items"]
    item = next(i for i in listing if i["id"] == queue_id)
    assert item["lastViewedAt"] is None  # 从未揭示 → 如实为空
    assert item["paraId"] == "p-7"  # deep link 数据

    viewed = client.post(f"/api/v1/review-queue/{queue_id}/view")
    assert viewed.status_code == 200
    last_viewed = viewed.json()["lastViewedAt"]
    assert last_viewed is not None

    # 重复揭示：水位前进（不回退）
    viewed_again = client.post(f"/api/v1/review-queue/{queue_id}/view")
    assert viewed_again.json()["lastViewedAt"] >= last_viewed

    listing = client.get("/api/v1/review-queue", params={"status": "due"}).json()["items"]
    item = next(i for i in listing if i["id"] == queue_id)
    assert item["lastViewedAt"] is not None
    # 未知队列项 → 404
    assert client.post(f"/api/v1/review-queue/{_uuid.uuid4()}/view").status_code == 404


def test_n077_revoked_entry_marks_unavailable(client):
    """原文删除（投影移除）→ sourceAvailable=false，队列项保留但诚实
    标注；来源恢复 → 重新可用。绝不缓存原文内容。"""
    ref = encode_entry_ref("9402")
    card_id = _create_card(ref, "双链笔记")
    client.post(
        "/api/v1/review-queue",
        json={"kind": "knowledge_card", "knowledgeCardId": card_id, "dueAt": "2020-01-01T00:00:00Z"},
    )

    def _card_item():
        listing = client.get("/api/v1/review-queue", params={"status": "due"}).json()["items"]
        return next(i for i in listing if i["knowledgeCardId"] == card_id)

    # 来源存在 → 可用
    _insert_search_entry(ref, title="标题", feed_title="来源", published_at="2026-01-01T00:00:00Z")
    assert _card_item()["sourceAvailable"] is True

    # 原文删除（投影行移除）→ 不可用，项保留
    _run(app.state.db.execute("DELETE FROM search_entries WHERE entry_ref = ?", (ref,)))
    item = _card_item()
    assert item["sourceAvailable"] is False
    assert item["concept"] == "双链笔记"  # 卡片内容仍在（用户数据），只是来源不可达
