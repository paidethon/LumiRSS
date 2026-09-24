"""N120 清理预演 —— 只读报告 + 选择性应用 + 快照撤销（规格逐条）。

- 预演准确列出：unresolved（feed/entry 消失）、受保护的 library 引用、
  unverifiable（上游不可用）、空组、悬空分节引用、固定+组冲突；
- apply 只移除列出的可执行类目行（绝不触碰 FreshRSS 数据、绝不删除
  library: 引用）；
- 快照先行（workspace_cleanup_log 上限 5）→ undo 恢复被移除的行。
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


def _entry_detail(item_id: str, title: str):
    from lumirss.models import EntryDetail

    return EntryDetail(
        entryRef=encode_entry_ref(item_id),
        title=title,
        feedTitle="测试源",
        url=f"https://example.com/{item_id}",
        publishedAt="2026-09-01T00:00:00+00:00",
        read=False,
        starred=False,
        contentText=f"{title} 的正文。",
        contentHtml=None,
    )


@pytest.fixture()
def rss_world(client):
    entries = {"6001": _entry_detail("6001", "会消失的条目")}
    adapter = _FakeAdapter(entries)
    app.state.freshrss_adapter = adapter
    yield entries
    app.state.freshrss_adapter = None


def _rss_ref(item_id: str) -> str:
    return "rss:" + encode_entry_ref(item_id)


def _category(preview_body, name):
    return next(c for c in preview_body["categories"] if c["category"] == name)


def _items(body, name):
    return _category(body, name)["items"]


# ===== 预演准确 ===============================================================


def test_n120_preview_lists_accurately(client, rss_world):
    ws = client.post("/api/v1/workspaces", json={"name": "清理预演"}).json()["id"]
    gone_ref = _rss_ref("6001")
    client.post(f"/api/v1/workspaces/{ws}/items", json={"itemRef": gone_ref})
    # 受保护 library 引用：书签 → 回收站（软删）→ 解析不到
    bm = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://gone-lib.example/1", "title": "库引用"},
    ).json()["ref"]
    client.post(f"/api/v1/workspaces/{ws}/items", json={"itemRef": bm})
    client.delete(f"/api/v1/library/bookmarks/{bm.removeprefix('library:')}")
    # 回收站彻底清除（软删的书签仍可解析；purge 后引用才真正悬空）
    purged = client.delete(
        f"/api/v1/library/trash/{bm.removeprefix('library:')}?permanent=true"
    )
    assert purged.status_code == 204, purged.text
    # 空组：先建组再移走成员（组名残留在 group_order_json）
    grouped = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://grouped.example/1", "title": "组员"},
    ).json()["ref"]
    client.post(
        f"/api/v1/workspaces/{ws}/items", json={"itemRef": grouped, "groupName": "旧组"}
    )
    client.put(f"/api/v1/workspaces/{ws}/groups", json={"order": ["旧组"]})
    client.delete(f"/api/v1/workspaces/{ws}/items/{grouped}")
    # 悬空分节引用（专属 ref：成员移出工作区后分节引用悬空）
    orphan_ref = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://orphan.example/1", "title": "将悬空"},
    ).json()["ref"]
    client.post(f"/api/v1/workspaces/{ws}/items", json={"itemRef": orphan_ref})
    section = client.post(
        f"/api/v1/workspaces/{ws}/sections", json={"title": "节"}
    ).json()
    client.post(
        f"/api/v1/workspaces/{ws}/sections/{section['id']}/items",
        json={"itemRef": orphan_ref},
    )
    client.delete(f"/api/v1/workspaces/{ws}/items/{orphan_ref}")
    # 固定 + 组冲突：固定行仍带组名（呈现冲突，只报告）
    pinny = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://pinny.example/1", "title": "固定组员"},
    ).json()["ref"]
    client.post(
        f"/api/v1/workspaces/{ws}/items", json={"itemRef": pinny, "groupName": "有组"}
    )
    client.put(f"/api/v1/workspaces/{ws}/items/{pinny}/pin", json={"pinned": True})

    # 上游条目消失
    del rss_world["6001"]
    preview = client.get(f"/api/v1/workspaces/{ws}/cleanup-preview")
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["actionable"] == [
        "unresolved_refs",
        "empty_groups",
        "orphan_section_refs",
    ]
    assert _items(body, "unresolved_refs")[0]["itemRef"] == gone_ref
    assert _items(body, "protected_library_refs")[0]["itemRef"] == bm
    assert _items(body, "empty_groups") == [
        {"name": "旧组", "reason": _items(body, "empty_groups")[0]["reason"]}
    ]
    orphan_items = _items(body, "orphan_section_refs")
    assert len(orphan_items) == 1 and orphan_items[0]["itemRef"] == orphan_ref
    conflicts = _items(body, "pinned_group_conflicts")
    assert conflicts and conflicts[0]["itemRef"] == pinny
    # 每一项都带原因（诚实报告）
    for category in body["categories"]:
        for item in category["items"]:
            assert item.get("reason")


def test_n120_preview_unverifiable_when_freshrss_unconfigured(client, rss_world):
    ws = client.post("/api/v1/workspaces", json={"name": "不可核实"}).json()["id"]
    ref = _rss_ref("6001")
    client.post(f"/api/v1/workspaces/{ws}/items", json={"itemRef": ref})
    # 条目从未进入投影 + 上游替身移除条目后适配器不可用 → unverifiable
    app.state.freshrss_adapter = None
    body = client.get(f"/api/v1/workspaces/{ws}/cleanup-preview").json()
    assert _items(body, "unverifiable_refs")[0]["itemRef"] == ref
    assert _items(body, "unresolved_refs") == []


# ===== 应用 + 撤销 ============================================================


def _prepare(client, rss_world):
    ws = client.post("/api/v1/workspaces", json={"name": "清理应用"}).json()["id"]
    gone_ref = _rss_ref("6001")
    client.post(f"/api/v1/workspaces/{ws}/items", json={"itemRef": gone_ref})
    bm = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://kept-lib.example/1", "title": "库引用"},
    ).json()["ref"]
    client.post(f"/api/v1/workspaces/{ws}/items", json={"itemRef": bm})
    client.delete(f"/api/v1/library/bookmarks/{bm.removeprefix('library:')}")
    client.delete(f"/api/v1/library/trash/{bm.removeprefix('library:')}?permanent=true")
    section = client.post(
        f"/api/v1/workspaces/{ws}/sections", json={"title": "节"}
    ).json()
    grouped = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://grouped2.example/1", "title": "组员"},
    ).json()["ref"]
    client.post(
        f"/api/v1/workspaces/{ws}/items", json={"itemRef": grouped, "groupName": "空组"}
    )
    client.put(f"/api/v1/workspaces/{ws}/groups", json={"order": ["空组"]})
    client.post(
        f"/api/v1/workspaces/{ws}/sections/{section['id']}/items",
        json={"itemRef": grouped},
    )
    client.delete(f"/api/v1/workspaces/{ws}/items/{grouped}")  # 成员移除 → 分节引用悬空
    del rss_world["6001"]
    return ws, gone_ref, bm, section["id"], grouped


def test_n120_apply_removes_only_listed(client, rss_world):
    ws, gone_ref, bm, section_id, _grouped = _prepare(client, rss_world)
    applied = client.post(
        f"/api/v1/workspaces/{ws}/cleanup",
        json={"categories": ["unresolved_refs", "empty_groups", "orphan_section_refs"]},
    )
    assert applied.status_code == 200, applied.text
    removed = applied.json()["removed"]
    assert removed["unresolvedRefs"] == 1
    assert removed["orphanSectionRefs"] == 1
    assert removed["emptyGroups"] == 1
    # stale rss 成员行被移除
    members = [
        m["itemRef"] for m in client.get(f"/api/v1/workspaces/{ws}/items").json()["items"]
    ]
    assert gone_ref not in members
    # library: 引用受保护：即使解析不到也绝不被移除
    assert bm in members
    # 悬空分节引用被移除；分节本身保留
    sections = client.get(f"/api/v1/workspaces/{ws}/sections").json()["items"]
    assert sections[0]["id"] == section_id
    assert sections[0]["items"] == []
    # 空组名从组顺序中移除
    groups = client.get(f"/api/v1/workspaces/{ws}/groups").json()
    assert "空组" not in groups["groupOrder"]
    # FreshRSS 数据绝不触碰（投影里不存在该条目行；适配器表原样）
    assert "6001" not in rss_world  # 上游条目仍然消失着，但没人替它「恢复」


def test_n120_apply_rejects_report_only_categories(client, rss_world):
    ws, *_ = _prepare(client, rss_world)
    for category in ("protected_library_refs", "unverifiable_refs", "made_up"):
        bad = client.post(
            f"/api/v1/workspaces/{ws}/cleanup", json={"categories": [category]}
        )
        assert bad.status_code == 422
        assert bad.json()["error"]["type"] == "invalid_workspace_cleanup"


def test_n120_undo_restores_removed(client, rss_world):
    ws, gone_ref, bm, section_id, grouped = _prepare(client, rss_world)
    # 把 6001 重新加入以便验证「stale 行」被删后可恢复（成员行删除与
    # 上游无关：行只是引用）。
    applied = client.post(
        f"/api/v1/workspaces/{ws}/cleanup",
        json={"categories": ["unresolved_refs", "orphan_section_refs", "empty_groups"]},
    )
    assert applied.status_code == 200
    log_id = applied.json()["logId"]
    undo = client.post(
        f"/api/v1/workspaces/{ws}/cleanup/undo", json={"logId": log_id}
    )
    assert undo.status_code == 200, undo.text
    assert undo.json()["restoredRefs"] == 1
    assert undo.json()["restoredSectionRefs"] == 1
    members = [
        m["itemRef"] for m in client.get(f"/api/v1/workspaces/{ws}/items").json()["items"]
    ]
    assert gone_ref in members  # rss 成员行恢复
    assert bm in members
    sections = client.get(f"/api/v1/workspaces/{ws}/sections").json()["items"]
    assert [i["itemRef"] for i in sections[0]["items"]] == [grouped]
    # 组顺序恢复
    groups = client.get(f"/api/v1/workspaces/{ws}/groups").json()
    assert "空组" in groups["groupOrder"]
    # 重复 undo 幂等（行已存在 → 跳过）
    undo_again = client.post(
        f"/api/v1/workspaces/{ws}/cleanup/undo", json={"logId": log_id}
    )
    assert undo_again.status_code == 200
    assert undo_again.json()["restoredRefs"] == 0


def test_n120_log_cap_five_and_latest_undo(client, rss_world):
    ws, *_ = _prepare(client, rss_world)
    ids = []
    for _ in range(6):
        applied = client.post(
            f"/api/v1/workspaces/{ws}/cleanup", json={"categories": ["unresolved_refs"]}
        )
        assert applied.status_code == 200
        ids.append(applied.json()["logId"])
    logs = client.get(f"/api/v1/workspaces/{ws}/cleanup-logs").json()["items"]
    assert len(logs) == 5  # 上限 5，最旧被淘汰
    assert ids[0] not in [log["id"] for log in logs]
    # 缺省 logId = 最近一条
    undo = client.post(f"/api/v1/workspaces/{ws}/cleanup/undo", json={})
    assert undo.status_code == 200
    assert undo.json()["logId"] == ids[-1]
    # 未知日志 → 404
    missing = client.post(
        f"/api/v1/workspaces/{ws}/cleanup/undo", json={"logId": "clean-nope"}
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "workspace_cleanup_log_not_found"
