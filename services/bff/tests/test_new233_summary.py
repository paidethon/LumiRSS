"""NEW-233 标注汇总阅读页 — 按文章结构汇总 / 回原段定位 / 隔离与有界。

- 单篇内按锚点块序号排序（p-1 → p-2 → p-10 数字典序而非字符串序）；
- 每条带 backHref（/reader?entry=…&para=…）点击回原段；绝不携带正文；
- entryRef 过滤 / 空 → 诚实空；文章数超上限 → truncated=true；
- 隔离：汇总只含本人标注。
"""

import asyncio

from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.user_scope import user_context


def _run(coroutine):
    return asyncio.run(coroutine)


def _annotation(client, entry_ref: str, para: str, excerpt: str) -> dict:
    response = client.post(
        "/api/v1/annotations",
        json={
            "entryRef": entry_ref,
            "anchor": {"paraId": para, "exact": excerpt, "prefix": "", "suffix": ""},
            "excerpt": excerpt,
            "note": f"关于{excerpt}的批注",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_new233_summary_orders_by_article_structure(client):
    """单篇内按块序号排序；跨篇分组；每条带回原段链接；无正文字段。"""
    ref = encode_entry_ref("9501")
    third = _annotation(client, ref, "p-10", "第三处标注（p-10）")
    first = _annotation(client, ref, "p-1", "第一处标注（p-1）")
    second = _annotation(client, ref, "p-2", "第二处标注（p-2）")
    _annotation(client, encode_entry_ref("9502"), "block-3", "另一篇的标注")

    summary = client.get("/api/v1/annotations/summary")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["totalAnnotations"] == 4
    assert body["entryCount"] == 2
    assert body["truncated"] is False

    by_ref = {entry["entryRef"]: entry for entry in body["entries"]}
    entry = by_ref[ref]
    ordered = [item["id"] for item in entry["annotations"]]
    assert ordered == [first["id"], second["id"], third["id"]]  # 结构序，非创建序
    assert entry["annotationCount"] == 3
    assert entry["annotations"][0]["backHref"].endswith(f"entry={ref}&para=p-1")
    assert entry["annotations"][0]["note"] == "关于第一处标注（p-1）的批注"
    # 不生成第二份正文：响应里没有正文字段
    assert "content" not in entry
    assert "contentText" not in entry
    assert "contentHtml" not in entry

    # 单篇过滤
    single = client.get("/api/v1/annotations/summary", params={"entryRef": ref})
    assert single.status_code == 200
    assert single.json()["entryCount"] == 1
    assert single.json()["totalAnnotations"] == 3

    # 空状态（该篇没有标注）→ 诚实空
    empty = client.get(
        "/api/v1/annotations/summary", params={"entryRef": encode_entry_ref("9599")}
    )
    assert empty.status_code == 200
    assert empty.json()["entries"] == []
    assert empty.json()["totalAnnotations"] == 0


def test_new233_summary_bounded_and_truncated_flag(client, monkeypatch):
    """文章数超上限 → truncated=true（诚实截断，不静默丢页）。"""
    import lumirss.new233_annotation_summary as summary_module

    for index in range(4):
        _annotation(
            client, encode_entry_ref(f"960{index}"), "p-0", f"第{index}篇摘录"
        )
    monkeypatch.setattr(summary_module, "MAX_SUMMARY_ENTRIES", 2)

    async def _build():
        with user_context(app.state.owner_id):
            store = summary_module  # noqa: F841 — monkeypatch 已生效
            from lumirss.annotation_store import AnnotationStore

            items, _ = await AnnotationStore(app.state.db).search(None, None)
            return await summary_module.build_summary(app.state.db, items)

    result = _run(_build())
    assert result["entryCount"] == 2
    assert result["truncated"] is True
    assert result["totalAnnotations"] == 4


def test_new233_cross_user_summary_isolated(monkeypatch, tmp_path):
    """A 的标注绝不进入 B 的汇总（per-user 库）。"""
    from new231_helpers import ab_session

    with ab_session(monkeypatch, tmp_path) as session:
        created = session.client.post(
            "/api/v1/annotations",
            json={
                "entryRef": "9700",
                "anchor": {"paraId": "p-0", "exact": "A 的摘录", "suffix": ""},
                "excerpt": "A 的摘录",
                "note": "A 的批注",
            },
            headers=session.owner,
        )
        assert created.status_code == 201
        member = session.activate_member("n233b")

        owner_summary = session.client.get(
            "/api/v1/annotations/summary", headers=session.owner
        )
        assert owner_summary.status_code == 200
        assert owner_summary.json()["totalAnnotations"] == 1

        member_summary = session.client.get(
            "/api/v1/annotations/summary", headers=member
        )
        assert member_summary.status_code == 200
        assert member_summary.json()["totalAnnotations"] == 0
        assert member_summary.json()["entries"] == []
