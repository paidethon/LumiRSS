"""N012 退订影响预览 —— 只读聚合 + 显式清理路径的 SQL 唯一入口。

预览（preview）在**任何** mutation 之前执行，只读派生投影与 Lumi 自有
元数据，回答「退订这个来源会动到什么」：

- workspaceItems：工作区里以 ``rss:<entryRef>`` 引用该来源条目的行
  （含看板状态行单独计数）；退订后这些引用变成「冻结 ref」——解析层
  已把缺失条目降级为 stale 卡片（workspaces.resolve_refs），不 500；
- libraryItems：library_bookmarks 中 item_type='rss' 指向该来源条目
  的书签（Lumi 自有对象，任何分支都不删）；
- annotations：锚定在该来源条目上的批注；
- unreadCount：派生投影中该来源未读条目数；
- inboxRules：enabled 且 field='source' 的收件箱规则中，按 rule_matches
  语义样本（订阅标题 / feed URL）会命中的规则（收件箱规则绑定的是
  收件连接器来源名；这里是对「会不会碰到这个来源」的诚实尽力判断）。

清理（purge_feed_artifacts）只在 DELETE 显式 ``keep_artifacts=false``
时执行：删除该来源条目的批注 + 工作区引用行（含看板状态行）。备注
（source_notes）沿用既有级联；library 书签不在此路径删除。
列表一律有界（≤50），计数与样本并列（count 如实，样本截断说明）。
"""

from typing import Any

from lumirss.storage import Database

_SAMPLE_LIMIT = 50


async def feed_entry_refs(db: Database, feed_url: str) -> list[str]:
    """该来源在派生投影中的全部 entry_ref（预览与清理共用；有界 5000）。"""
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT entry_ref FROM search_entries WHERE feed_url = ? LIMIT 5000",
        (feed_url,),
    )
    return [str(row["entry_ref"]) for row in rows]


async def unread_count(db: Database, feed_url: str) -> int:
    await db.migrate()
    row = await db.fetch_one(
        "SELECT COUNT(*) AS n FROM search_entries WHERE feed_url = ? AND read = 0",
        (feed_url,),
    )
    return int(row["n"]) if row is not None else 0


async def workspace_items_for(db: Database, refs: list[str]) -> dict[str, Any]:
    """引用该来源条目的工作区行（计数 + ≤50 样本，工作区名一并返回）。"""
    if not refs:
        return {"count": 0, "items": []}
    await db.migrate()
    wired = [f"rss:{ref}" for ref in refs]
    placeholders = ",".join("?" for _ in wired)
    rows = await db.fetch_all(
        f"SELECT wi.workspace_id, wi.item_ref, w.name AS workspace_name FROM workspace_items wi LEFT JOIN workspaces w ON w.id = wi.workspace_id WHERE wi.item_ref IN ({placeholders}) LIMIT 5000",
        tuple(wired),
    )
    items = [
        {
            "workspaceId": str(row["workspace_id"]),
            "workspaceName": str(row["workspace_name"] or ""),
            "itemRef": str(row["item_ref"]),
        }
        for row in rows
    ]
    return {"count": len(items), "items": items[:_SAMPLE_LIMIT]}


async def board_items_for(db: Database, refs: list[str]) -> dict[str, Any]:
    """该来源条目的看板状态行（workspace_item_status；计数 + ≤50 样本）。"""
    if not refs:
        return {"count": 0, "items": []}
    await db.migrate()
    wired = [f"rss:{ref}" for ref in refs]
    placeholders = ",".join("?" for _ in wired)
    rows = await db.fetch_all(
        f"SELECT workspace_id, item_ref, status FROM workspace_item_status WHERE item_ref IN ({placeholders}) LIMIT 5000",
        tuple(wired),
    )
    items = [
        {
            "workspaceId": str(row["workspace_id"]),
            "itemRef": str(row["item_ref"]),
            "status": str(row["status"]),
        }
        for row in rows
    ]
    return {"count": len(items), "items": items[:_SAMPLE_LIMIT]}


async def library_items_for(db: Database, refs: list[str]) -> dict[str, Any]:
    """指向该来源条目的 RSS 书签（library_bookmarks；计数 + ≤50 样本）。"""
    if not refs:
        return {"count": 0, "items": []}
    await db.migrate()
    wired = [f"rss:{ref}" for ref in refs]
    placeholders = ",".join("?" for _ in wired)
    rows = await db.fetch_all(
        f"SELECT item_uuid, rss_item_ref, title FROM library_bookmarks WHERE rss_item_ref IN ({placeholders}) LIMIT 5000",
        tuple(wired),
    )
    items = [
        {
            "itemRef": f"library:{row['item_uuid']}",
            "rssItemRef": str(row["rss_item_ref"]),
            "title": str(row["title"]),
        }
        for row in rows
    ]
    return {"count": len(items), "items": items[:_SAMPLE_LIMIT]}


async def annotations_for(db: Database, refs: list[str]) -> dict[str, Any]:
    """锚定在该来源条目上的批注（计数 + ≤50 样本）。"""
    if not refs:
        return {"count": 0, "items": []}
    await db.migrate()
    placeholders = ",".join("?" for _ in refs)
    rows = await db.fetch_all(
        f"SELECT id, entry_ref, excerpt FROM annotations WHERE entry_ref IN ({placeholders}) LIMIT 5000",
        tuple(refs),
    )
    items = [
        {
            "id": str(row["id"]),
            "entryRef": str(row["entry_ref"]),
            "excerpt": str(row["excerpt"] or ""),
        }
        for row in rows
    ]
    return {"count": len(items), "items": items[:_SAMPLE_LIMIT]}


async def touching_inbox_rules(
    db: Database, title: str, feed_url: str
) -> dict[str, Any]:
    """会命中该订阅样本（标题 / feed URL）的 enabled source 规则。

    收件箱规则的 source 维度绑定收件连接器来源名；RSS 订阅只是按同一
    匹配语义的「尽力判断」，诚实标注在路由层文案里。"""
    from lumirss.inbox_rules import rule_matches

    await db.migrate()
    rows = await db.fetch_all(
        "SELECT id, priority, field, operator, value, enabled FROM inbox_rules WHERE enabled = 1 ORDER BY priority, id"
    )
    items = []
    for row in rows:
        rule = {
            "enabled": bool(row["enabled"]),
            "field": str(row["field"]),
            "value": str(row["value"]),
            "operator": str(row["operator"]),
        }
        for sample in (title, feed_url):
            if sample and rule_matches(rule, field="source", value=sample, source=sample):
                items.append(
                    {
                        "id": int(row["id"]),
                        "field": rule["field"],
                        "operator": rule["operator"],
                        "value": rule["value"],
                        "matchedSample": "title" if sample == title else "feedUrl",
                    }
                )
                break
    return {"count": len(items), "items": items[:_SAMPLE_LIMIT]}


async def build_preview(db: Database, feed_url: str, title: str) -> dict[str, Any]:
    """聚合全部影响维度（纯只读；调用方在任何 mutation 之前调用）。"""
    refs = await feed_entry_refs(db, feed_url)
    return {
        "feedUrl": feed_url,
        "title": title,
        "projectionEntries": len(refs),
        "unreadCount": await unread_count(db, feed_url),
        "workspaceItems": await workspace_items_for(db, refs),
        "boardItems": await board_items_for(db, refs),
        "libraryItems": await library_items_for(db, refs),
        "annotations": await annotations_for(db, refs),
        "inboxRules": await touching_inbox_rules(db, title, feed_url),
        "sampleLimit": _SAMPLE_LIMIT,
    }


async def purge_feed_artifacts(db: Database, feed_url: str) -> dict[str, int]:
    """DELETE keep_artifacts=false 的显式清理：批注 + 工作区引用（含看板
    状态行）。返回各维度删除计数（诚实汇报）。library 书签不在路径内。"""
    refs = await feed_entry_refs(db, feed_url)
    if not refs:
        return {"annotations": 0, "workspaceItems": 0, "boardItems": 0}
    placeholders = ",".join("?" for _ in refs)
    wired = [f"rss:{ref}" for ref in refs]
    wired_ph = ",".join("?" for _ in wired)
    await db.migrate()
    ann = await db.fetch_one(
        f"SELECT COUNT(*) AS n FROM annotations WHERE entry_ref IN ({placeholders})",
        tuple(refs),
    )
    board = await db.fetch_one(
        f"SELECT COUNT(*) AS n FROM workspace_item_status WHERE item_ref IN ({wired_ph})",
        tuple(wired),
    )
    items = await db.fetch_one(
        f"SELECT COUNT(*) AS n FROM workspace_items WHERE item_ref IN ({wired_ph})",
        tuple(wired),
    )
    await db.execute(
        f"DELETE FROM workspace_item_status WHERE item_ref IN ({wired_ph})",
        tuple(wired),
    )
    await db.execute(
        f"DELETE FROM workspace_items WHERE item_ref IN ({wired_ph})",
        tuple(wired),
    )
    await db.execute(
        f"DELETE FROM annotations WHERE entry_ref IN ({placeholders})",
        tuple(refs),
    )
    return {
        "annotations": int(ann["n"]) if ann else 0,
        "workspaceItems": int(items["n"]) if items else 0,
        "boardItems": int(board["n"]) if board else 0,
    }
