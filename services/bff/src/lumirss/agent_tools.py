"""Agent tool wiring (phase2 G7): the whitelist against real services.

Read tools: search (RSS+library projections), rag_search, get_entry,
get_library_item, list_notes. Write tools: add_to_workspace,
save_bookmark, add_tag (G8) — executed only post-approval through the
same service path the UI uses, so persistence is real and restart-safe.
"""

from lumirss.agent_store import ToolRegistry
from lumirss.itemref import parse_item_ref
from lumirss.sources import excerpt_of


def build_registry(**services) -> ToolRegistry:
    """services: search_writer(RSS), library_search(LibrarySearchWriter),
    rag(RagService), adapter(FreshRSSAdapter|None), library(LibraryStore),
    workspaces(WorkspaceStore)."""
    registry = ToolRegistry()
    rss_search = services["rss_search"]
    library_search = services["library_search"]
    rag = services["rag"]
    adapter = services.get("adapter")
    library = services["library"]
    workspaces = services["workspaces"]

    async def tool_search(args: dict) -> dict:
        query = str(args.get("query") or "").strip()[:200]
        rss_rows = await rss_search(query, 5)
        lib_rows = await library_search.search(query, limit=5)
        citations = [row["entry_ref"] for row in rss_rows] + [
            row["ref"] for row in lib_rows
        ]
        return {
            "results": [
                {"title": r["title"], "snippet": (r["content_text"] or "")[:160]}
                for r in rss_rows
            ]
            + [
                {"title": r["title"], "snippet": (r["body"] or "")[:160]}
                for r in lib_rows
            ],
            "citations": citations,
        }

    async def tool_rag_search(args: dict) -> dict:
        query = str(args.get("query") or "").strip()[:200]
        result = await rag.search(query, k=int(args.get("k") or 6))
        refs = [item["ref"] for item in result["items"]]
        return {
            "results": [
                {
                    "ref": item["ref"],
                    "text": item["text"][:300],
                    "score": round(item["score"], 4),
                }
                for item in result["items"]
            ],
            "semanticUsed": result["semanticUsed"],
            "citations": refs,
        }

    async def tool_get_entry(args: dict) -> dict:
        if adapter is None:
            return {"error": "RSS 未配置"}
        from lumirss.entryref import decode_entry_ref

        detail = await adapter.get_entry(decode_entry_ref(str(args.get("entryRef", ""))))
        return {
            "title": detail.title,
            "feedTitle": detail.feedTitle,
            "text": detail.contentText[:1500],
        }

    async def tool_get_library_item(args: dict) -> dict:
        view = await library.get_library_item(str(args.get("itemRef", "")).split(":")[-1])
        if view is None:
            return {"error": "not_found"}
        return {
            "title": view.title,
            "note": view.note[:300],
            "url": view.url,
        }

    async def tool_list_notes(args: dict) -> dict:
        obsidian = services.get("obsidian")
        if obsidian is None:
            return {"notes": []}
        query = str(args.get("query") or "").strip()
        notes = await obsidian.list_notes(q=query or None, limit=5)
        return {
            "notes": [
                {"title": n["title"], "relPath": n["relPath"], "ref": n["ref"]}
                for n in notes
            ]
        }

    async def tool_add_to_workspace(args: dict) -> dict:
        workspace_id = str(args.get("workspaceId") or "read-later")
        item_ref = parse_item_ref(str(args.get("itemRef") or "")).format()
        item = await workspaces.add_item(workspace_id, item_ref)
        return {"added": True, "workspaceId": workspace_id, "position": item.position}

    async def tool_save_bookmark(args: dict) -> dict:
        rss_item_ref = args.get("rssItemRef")
        if rss_item_ref:
            view, created = await library.create_rss_bookmark(
                parse_item_ref(str(rss_item_ref)).format(),
                str(args.get("title") or "未命名"),
            )
        else:
            view, created = await library.create_url_bookmark(
                str(args.get("url") or ""),
                str(args.get("title") or "未命名"),
            )
        return {"ref": view.ref, "created": created}

    registry.register_read(
        "search",
        "跨 RSS 与知识库全文搜索（关键词）",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        tool_search,
    )
    registry.register_read(
        "rag_search",
        "语义混合检索（向量+关键词，未启用时自动降级关键词）",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "k": {"type": "integer"},
            },
            "required": ["query"],
        },
        tool_rag_search,
    )
    registry.register_read(
        "get_entry",
        "读取一篇 RSS 文章的标题与正文文本",
        {
            "type": "object",
            "properties": {"entryRef": {"type": "string"}},
            "required": ["entryRef"],
        },
        tool_get_entry,
    )
    registry.register_read(
        "get_library_item",
        "读取一个库条目（书签/剪藏等）的元数据",
        {
            "type": "object",
            "properties": {"itemRef": {"type": "string"}},
            "required": ["itemRef"],
        },
        tool_get_library_item,
    )
    registry.register_read(
        "list_notes",
        "按关键词列出 Obsidian 笔记（只读投影）",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
        tool_list_notes,
    )
    registry.register_write(
        "add_to_workspace",
        "把一个条目（ItemRef）加入指定工作区（默认稍后读）",
        {
            "type": "object",
            "properties": {
                "itemRef": {"type": "string"},
                "workspaceId": {"type": "string"},
            },
            "required": ["itemRef"],
        },
        tool_add_to_workspace,
    )
    registry.register_write(
        "save_bookmark",
        "保存书签（RSS 引用或 URL）",
        {
            "type": "object",
            "properties": {
                "rssItemRef": {"type": "string"},
                "url": {"type": "string"},
                "title": {"type": "string"},
            },
        },
        tool_save_bookmark,
    )
    async def tool_add_tag(args: dict) -> dict:
        tag_store = services["tags"]
        item_ref = parse_item_ref(str(args.get("itemRef") or "")).format()
        binding = await tag_store.attach(
            item_ref, str(args.get("name") or ""), origin="manual"
        )
        return {"tagged": True, "name": binding["name"], "ref": binding["ref"]}

    registry.register_write(
        "add_tag",
        "给一个条目（ItemRef）打一个手动标签",
        {
            "type": "object",
            "properties": {
                "itemRef": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["itemRef", "name"],
        },
        tool_add_tag,
    )
    _ = excerpt_of  # reserved for future excerpt tools
    return registry
