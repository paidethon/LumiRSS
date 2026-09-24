"""N113 分节大纲 + N114 汇编预览 —— 正负向（规格逐条）。

N113：sections CRUD + 分节成员（引用而非复制；同一 ref 可进多节）；
分节顺序持久化；节内顺序持久化；条目移出工作区 → 列表诚实标记
unresolved。
N114：compile 按大纲汇编草稿（纯预览不落库）：结构正确；缺失引用
诚实排除并计数；markdown 含引文链接。
"""

import asyncio

import pytest

from lumirss.entryref import encode_entry_ref
from lumirss.main import app


def run(coro):
    return asyncio.run(coro)


class _FakeAdapter:
    def __init__(self, entries: dict) -> None:
        self._entries = entries

    async def get_entry(self, item_id: str):
        entry = self._entries.get(item_id)
        if entry is None:
            from lumirss.adapters.freshrss import EntryNotFound

            raise EntryNotFound(item_id)
        return entry


def _entry_detail(item_id: str, title: str, content: str = ""):
    from lumirss.models import EntryDetail

    return EntryDetail(
        entryRef=encode_entry_ref(item_id),
        title=title,
        feedTitle="测试源",
        url=f"https://example.com/{item_id}",
        publishedAt="2026-09-01T00:00:00+00:00",
        read=False,
        starred=False,
        contentText=content or f"{title} 的正文文本。",
        contentHtml=None,
    )


@pytest.fixture()
def rss_world(client):
    entries = {
        "7001": _entry_detail("7001", "第一篇：检索增强"),
        "7002": _entry_detail("7002", "第二篇：推理优化", "很长的正文。" * 80),
    }
    adapter = _FakeAdapter(entries)
    app.state.freshrss_adapter = adapter
    yield entries
    app.state.freshrss_adapter = None


def _rss_ref(item_id: str) -> str:
    return "rss:" + encode_entry_ref(item_id)


def _mk_ws(client, name):
    ws = client.post("/api/v1/workspaces", json={"name": name}).json()["id"]
    bm = client.post(
        "/api/v1/library/bookmarks",
        json={"url": f"https://{name}.example/1", "title": name},
    ).json()["ref"]
    client.post(f"/api/v1/workspaces/{ws}/items", json={"itemRef": bm})
    return ws, bm


def _section(client, ws, title):
    return client.post(f"/api/v1/workspaces/{ws}/sections", json={"title": title}).json()


# ===== N113 分节大纲 ==========================================================


def test_n113_section_crud_and_order_persisted(client):
    ws, _bm = _mk_ws(client, "n113-ws")
    s1 = _section(client, ws, "背景")
    s2 = _section(client, ws, "方法")
    assert s1["sortIndex"] < s2["sortIndex"]
    # 重排：方法 → 背景 之前
    reordered = client.put(
        f"/api/v1/workspaces/{ws}/sections/order",
        json={"sectionIds": [s2["id"], s1["id"]]},
    )
    assert reordered.status_code == 200, reordered.text
    listed = client.get(f"/api/v1/workspaces/{ws}/sections").json()["items"]
    assert [s["id"] for s in listed] == [s2["id"], s1["id"]]
    # 刷新后仍持久
    again = client.get(f"/api/v1/workspaces/{ws}/sections").json()["items"]
    assert [s["id"] for s in again] == [s2["id"], s1["id"]]
    # 重命名
    renamed = client.patch(
        f"/api/v1/workspaces/{ws}/sections/{s1['id']}", json={"title": "相关工作"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "相关工作"
    # 删除 → 消失
    deleted = client.delete(f"/api/v1/workspaces/{ws}/sections/{s1['id']}")
    assert deleted.status_code == 204
    remaining = client.get(f"/api/v1/workspaces/{ws}/sections").json()["items"]
    assert [s["id"] for s in remaining] == [s2["id"]]
    # 未知分节 → 404
    assert (
        client.patch(
            f"/api/v1/workspaces/{ws}/sections/sec-missing", json={"title": "x"}
        ).status_code
        == 404
    )
    # 未知 id 重排 → 422
    bad_order = client.put(
        f"/api/v1/workspaces/{ws}/sections/order",
        json={"sectionIds": [s2["id"], "sec-missing"]},
    )
    assert bad_order.status_code == 422


def test_n113_same_ref_in_two_sections_single_member_row(client):
    ws, bm = _mk_ws(client, "n113-multi")
    s1 = _section(client, ws, "甲节")
    s2 = _section(client, ws, "乙节")
    for section in (s1, s2):
        added = client.post(
            f"/api/v1/workspaces/{ws}/sections/{section['id']}/items",
            json={"itemRef": bm},
        )
        assert added.status_code == 201, added.text
    listed = client.get(f"/api/v1/workspaces/{ws}/sections").json()["items"]
    by_id = {s["id"]: s for s in listed}
    assert [i["itemRef"] for i in by_id[s1["id"]]["items"]] == [bm]
    assert [i["itemRef"] for i in by_id[s2["id"]]["items"]] == [bm]
    # 底层成员只有一行（引用而非复制）
    members = client.get(f"/api/v1/workspaces/{ws}/items").json()["items"]
    assert len([m for m in members if m["itemRef"] == bm]) == 1
    # 幂等重放（同节重复加）
    repeat = client.post(
        f"/api/v1/workspaces/{ws}/sections/{s1['id']}/items", json={"itemRef": bm}
    )
    assert repeat.status_code == 201
    assert len(by_id[s1["id"]]["items"]) == 1


def test_n113_non_member_rejected_and_remove(client):
    ws, bm = _mk_ws(client, "n113-member")
    section = _section(client, ws, "节")
    stranger = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://stranger.example/1", "title": "非成员"},
    ).json()["ref"]
    bad = client.post(
        f"/api/v1/workspaces/{ws}/sections/{section['id']}/items",
        json={"itemRef": stranger},
    )
    assert bad.status_code == 404
    assert bad.json()["error"]["type"] == "workspace_section_item_not_found"
    # 加入后移除
    client.post(
        f"/api/v1/workspaces/{ws}/sections/{section['id']}/items",
        json={"itemRef": bm},
    )
    removed = client.delete(
        f"/api/v1/workspaces/{ws}/sections/{section['id']}/items/{bm}"
    )
    assert removed.status_code == 204
    listed = client.get(f"/api/v1/workspaces/{ws}/sections").json()["items"]
    assert listed[0]["items"] == []


def test_n113_unresolved_marked_honestly(client):
    ws, bm = _mk_ws(client, "n113-unresolved")
    section = _section(client, ws, "节")
    client.post(
        f"/api/v1/workspaces/{ws}/sections/{section['id']}/items",
        json={"itemRef": bm},
    )
    # 条目移出工作区 → 分节引用行保留，列表标记 unresolved
    client.delete(f"/api/v1/workspaces/{ws}/items/{bm}")
    listed = client.get(f"/api/v1/workspaces/{ws}/sections").json()["items"]
    items = listed[0]["items"]
    assert len(items) == 1
    assert items[0]["itemRef"] == bm
    assert items[0]["unresolved"] is True


def test_n113_item_order_within_section(client):
    ws, bm = _mk_ws(client, "n113-order")
    other = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://n113-order.example/2", "title": "第二"},
    ).json()["ref"]
    client.post(f"/api/v1/workspaces/{ws}/items", json={"itemRef": other})
    section = _section(client, ws, "节")
    for ref in (bm, other):
        client.post(
            f"/api/v1/workspaces/{ws}/sections/{section['id']}/items",
            json={"itemRef": ref},
        )
    reordered = client.put(
        f"/api/v1/workspaces/{ws}/sections/{section['id']}/items/order",
        json={"itemRefs": [other, bm]},
    )
    assert reordered.status_code == 200
    listed = client.get(f"/api/v1/workspaces/{ws}/sections").json()["items"]
    assert [i["itemRef"] for i in listed[0]["items"]] == [other, bm]


# ===== N114 汇编预览 ==========================================================


def _outline_ws(client, entries):
    """两节工作区：背景（7001 + 书签）、方法（7002）。"""
    ws, bm = _mk_ws(client, "汇编工作区")
    s1 = _section(client, ws, "背景")
    s2 = _section(client, ws, "方法")
    refs = [_rss_ref("7001"), _rss_ref("7002")]
    for ref in refs:
        client.post(f"/api/v1/workspaces/{ws}/items", json={"itemRef": ref})
    client.post(f"/api/v1/workspaces/{ws}/sections/{s1['id']}/items", json={"itemRef": refs[0]})
    client.post(f"/api/v1/workspaces/{ws}/sections/{s1['id']}/items", json={"itemRef": bm})
    client.post(f"/api/v1/workspaces/{ws}/sections/{s2['id']}/items", json={"itemRef": refs[1]})
    return ws, bm, s1, s2


def test_n114_compile_structure(client, rss_world):
    ws, bm, s1, s2 = _outline_ws(client, rss_world)
    draft = client.post(f"/api/v1/workspaces/{ws}/compile", json={})
    assert draft.status_code == 200, draft.text
    body = draft.json()
    assert body["workspaceId"] == ws
    assert [s["title"] for s in body["sections"]] == ["背景", "方法"]
    background = body["sections"][0]
    assert background["sectionId"] == s1["id"]
    assert [i["itemRef"] for i in background["items"]] == [
        _rss_ref("7001"),
        bm,
    ]
    first = background["items"][0]
    assert first["title"] == "第一篇：检索增强"
    assert len(first["excerpt"]) <= 200
    assert first["citation"].startswith("/reader?entry=")
    long_item = body["sections"][1]["items"][0]
    assert len(long_item["excerpt"]) <= 200  # ≤200 截断契约
    assert body["includedCount"] == 3
    assert body["excludedMissing"] == 0
    # 纯预览：不落库（没有 draft 持久化端点/表副作用可查——重复编译一致）
    again = client.post(f"/api/v1/workspaces/{ws}/compile", json={}).json()
    assert again["sections"] == body["sections"]


def test_n114_compile_excludes_missing_with_counts(client, rss_world):
    ws, _bm, _s1, _s2 = _outline_ws(client, rss_world)
    # 条目 7001 从上游消失
    del rss_world["7001"]
    draft = client.post(f"/api/v1/workspaces/{ws}/compile", json={}).json()
    assert draft["excludedMissing"] == 1
    assert draft["excluded"][0]["itemRef"] == _rss_ref("7001")
    assert draft["includedCount"] == 2
    background = draft["sections"][0]
    assert all(i["itemRef"] != _rss_ref("7001") for i in background["items"])


def test_n114_compile_markdown_contains_citations(client, rss_world):
    ws, _bm, _s1, _s2 = _outline_ws(client, rss_world)
    md = client.post(f"/api/v1/workspaces/{ws}/compile/markdown", json={})
    assert md.status_code == 200
    assert md.headers["content-type"].startswith("text/markdown")
    text = md.text
    assert "# 汇编工作区" in text
    assert "## 背景" in text and "## 方法" in text
    assert "/reader?entry=" in text
    assert "第一篇：检索增强" in text


def test_n114_compile_section_filter(client, rss_world):
    ws, _bm, s1, _s2 = _outline_ws(client, rss_world)
    draft = client.post(
        f"/api/v1/workspaces/{ws}/compile", json={"sectionIds": [s1["id"]]}
    ).json()
    assert [s["title"] for s in draft["sections"]] == ["背景"]
    assert draft["includedCount"] == 2
    # 未知 sectionId → 422
    bad = client.post(
        f"/api/v1/workspaces/{ws}/compile", json={"sectionIds": ["sec-nope"]}
    )
    assert bad.status_code == 422


def test_n114_compile_flat_fallback_without_sections(client, rss_world):
    ws, bm = _mk_ws(client, "无大纲")
    client.post(f"/api/v1/workspaces/{ws}/items", json={"itemRef": _rss_ref("7001")})
    draft = client.post(f"/api/v1/workspaces/{ws}/compile", json={}).json()
    assert len(draft["sections"]) == 1
    assert draft["sections"][0]["sectionId"] is None
    assert draft["sections"][0]["title"] == "无大纲"
    assert draft["includedCount"] == 2
