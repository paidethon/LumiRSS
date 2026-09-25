"""Agent tool wiring (phase2 G7): the whitelist against real services.

Read tools: search (RSS+library projections), rag_search, get_entry,
get_library_item, list_notes. Write tools: add_to_workspace,
save_bookmark, add_tag (G8) — executed only post-approval through the
same service path the UI uses, so persistence is real and restart-safe.

W5（F094/F097）：
- 范围锁定：registry.context["scope"] 存在时，search/rag_search 在
  服务端过滤结果至范围内（工作区成员或 entryRefs 列表）；空范围
  诚实报错（scope_empty）；无范围时行为不变。
- dry-run：build_dry_run 提供写工具的零写入预演（F097 预演端点用）。
"""

from lumirss.agent_store import ToolRegistry
from lumirss.itemref import parse_item_ref
from lumirss.sources import excerpt_of
from lumirss.workspaces import RESERVED_WORKSPACE_ID


class DryRunUnsupported(Exception):
    """只读工具没有预演（F097：404/422 诚实返回）。"""


def build_registry(**services) -> ToolRegistry:
    """services: search_writer(RSS), library_search(LibrarySearchWriter),
    rag(RagService), adapter(FreshRSSAdapter|None), library(LibraryStore),
    workspaces(WorkspaceStore), db(Database — F066 来源 AI 禁用过滤用)."""
    registry = ToolRegistry()
    rss_search = services["rss_search"]
    library_search = services["library_search"]
    rag = services["rag"]
    adapter = services.get("adapter")
    library = services["library"]
    workspaces = services["workspaces"]

    db = services["db"]

    async def _drop_ai_disabled(refs: list[str]) -> set[str]:
        from lumirss.source_ai_gate import disabled_entry_refs

        return await disabled_entry_refs(db, refs)

    async def _scope_allowed_refs(refs: list[str]) -> set[str] | None:
        """F094：会话范围 → 允许的 ref 集合（None = 未锁定）。"""
        scope = registry.context.get("scope")
        if not scope:
            return None
        from lumirss.agent_scope import allowed_refs_for_scope

        allowed = await allowed_refs_for_scope(db, workspaces, scope)
        return allowed

    async def _filter_by_scope(refs: list[str]) -> list[str]:
        allowed = await _scope_allowed_refs(refs)
        if allowed is None:
            return refs
        return [r for r in refs if r in allowed]

    async def _effective_scope() -> dict:
        """N151：查询时服务端解析 {kind, refCount}（范围回显）。"""
        from lumirss.agent_scope import effective_scope

        return await effective_scope(db, workspaces, registry.context.get("scope"))

    async def tool_search(args: dict) -> dict:
        query = str(args.get("query") or "").strip()[:200]
        rss_rows = await rss_search(query, 5)
        # F066：AI 禁用来源的条目不进入 agent 结果。
        disabled = await _drop_ai_disabled([str(r["entry_ref"]) for r in rss_rows])
        if disabled:
            rss_rows = [r for r in rss_rows if str(r["entry_ref"]) not in disabled]
        lib_rows = await library_search.search(query, limit=5)
        rss_refs = [str(row["entry_ref"]) for row in rss_rows]
        lib_refs = [str(row["ref"]) for row in lib_rows]
        # F094：会话范围锁定 → 服务端过滤（资料文本无法绕过）。
        rss_keep = await _filter_by_scope(rss_refs)
        lib_keep = await _filter_by_scope(lib_refs)
        scope = registry.context.get("scope")
        if scope is not None and not rss_keep and not lib_keep:
            return {"error": "scope_empty", "results": [], "citations": []}
        citations = rss_keep + lib_keep
        return {
            "results": [
                {"title": r["title"], "snippet": (r["content_text"] or "")[:160]}
                for r, ref in zip(rss_rows, rss_refs, strict=False)
                if ref in set(rss_keep)
            ]
            + [
                {"title": r["title"], "snippet": (r["body"] or "")[:160]}
                for r, ref in zip(lib_rows, lib_refs, strict=False)
                if ref in set(lib_keep)
            ],
            "citations": citations,
        }

    async def tool_rag_search(args: dict) -> dict:
        query = str(args.get("query") or "").strip()[:200]
        result = await rag.search(query, k=int(args.get("k") or 6))
        # F066：AI 禁用来源的条目从结果中过滤。
        from lumirss.source_ai_gate import disabled_entry_refs

        rag_refs = [item["ref"] for item in result["items"]]
        disabled_refs = await disabled_entry_refs(db, rag_refs)
        if disabled_refs:
            result = {
                **result,
                "items": [i for i in result["items"] if i["ref"] not in disabled_refs],
            }
        # F094：会话范围锁定 → 服务端过滤。
        kept_refs = await _filter_by_scope([i["ref"] for i in result["items"]])
        result = {
            **result,
            "items": [i for i in result["items"] if i["ref"] in set(kept_refs)],
        }
        # N151：授权范围回显（查询时服务端解析 kind × refCount）。
        effective = await _effective_scope()
        scope = registry.context.get("scope")
        if scope is not None and not result["items"]:
            return {
                "error": "scope_empty",
                "results": [],
                "semanticUsed": result["semanticUsed"],
                "effectiveScope": effective,
                "citations": [],
            }
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
            "effectiveScope": effective,
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

    async def tool_list_workspace_items(args: dict) -> dict:
        # Read-only enumeration (P0-08g): the model can see what a
        # workspace already contains before suggesting add_to_workspace.
        workspace_id = str(args.get("workspaceId") or RESERVED_WORKSPACE_ID)
        summary = await workspaces.get_workspace(workspace_id)
        if summary is None:
            return {"error": "workspace_not_found", "workspaceId": workspace_id}
        items = await workspaces.list_items(workspace_id, limit=50)
        return {
            "workspaceId": workspace_id,
            "name": summary.name,
            "items": [
                {"itemRef": item.item_ref, "position": item.position}
                for item in items
            ],
            "citations": [item.item_ref for item in items],
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
    registry.register_read(
        "list_workspace_items",
        "列出一个工作区内的条目（默认稍后读），返回 ItemRef 列表",
        {
            "type": "object",
            "properties": {"workspaceId": {"type": "string"}},
        },
        tool_list_workspace_items,
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


# -- F097 写操作预演（dry-run，零业务写入）-------------------------------------


def build_dry_run(**services):
    """返回 ``async def dry_run(tool, args) -> dict``。

    每个写工具一个纯读分支：说明目标与逐字段变化（from → to）与
    不确定项；绝不执行业务写入（预演前后 DB 状态不变——负向断言）。
    只读/未知工具 → DryRunUnsupported（路由层 422/404 诚实返回）。"""
    library = services["library"]
    workspaces = services["workspaces"]

    async def dry_run_add_to_workspace(args: dict) -> dict:
        workspace_id = str(args.get("workspaceId") or RESERVED_WORKSPACE_ID)
        summary = await workspaces.get_workspace(workspace_id)
        if summary is None:
            return {
                "target": f"workspace:{workspace_id}",
                "changes": [],
                "uncertain": ["目标工作区不存在（执行时将失败）"],
            }
        raw_ref = str(args.get("itemRef") or "")
        try:
            item_ref = parse_item_ref(raw_ref).format()
        except ValueError:
            item_ref = raw_ref
        members = {
            item.item_ref for item in await workspaces.list_items(workspace_id, limit=500)
        }
        already = item_ref in members
        return {
            "target": f"workspace:{workspace_id}（{summary.name}）",
            "changes": (
                []
                if already
                else [
                    {
                        "field": "membership",
                        "from": "absent",
                        "to": item_ref,
                    }
                ]
            ),
            "uncertain": [] if not already else ["条目已在工作区中（幂等重复）"],
        }

    async def dry_run_save_bookmark(args: dict) -> dict:
        rss_item_ref = args.get("rssItemRef")
        url = args.get("url")
        existing = None
        if rss_item_ref:
            from lumirss.itemref import parse_item_ref as _p

            existing = await library._find_by_rss_ref(  # noqa: SLF001
                _p(str(rss_item_ref)).format()
            )
        elif url:
            existing = await library._find_by_url(str(url))  # noqa: SLF001
        title = str(args.get("title") or "未命名")
        if existing is not None:
            return {
                "target": f"library:{existing.ref}",
                "changes": [],
                "uncertain": ["同 URL/引用的书签已存在（幂等返回既有）"],
            }
        return {
            "target": "library:<new>",
            "changes": [
                {"field": "kind", "from": None, "to": "bookmark"},
                {"field": "title", "from": None, "to": title},
                {
                    "field": "source",
                    "from": None,
                    "to": str(rss_item_ref or url),
                },
            ],
            "uncertain": [],
        }

    async def dry_run_add_tag(args: dict) -> dict:
        tags = services["tags"]
        raw_ref = str(args.get("itemRef") or "")
        name = str(args.get("name") or "")
        try:
            item_ref = parse_item_ref(raw_ref).format()
        except ValueError:
            item_ref = raw_ref
        current = {t["name"] for t in await tags.tags_for_item(item_ref)}
        return {
            "target": item_ref,
            "changes": (
                []
                if name in current
                else [{"field": "tag", "from": None, "to": name}]
            ),
            "uncertain": [] if name not in current else ["标签已存在（幂等）"],
        }

    async def dry_run(tool: str, args: dict) -> dict:
        handlers = {
            "add_to_workspace": dry_run_add_to_workspace,
            "save_bookmark": dry_run_save_bookmark,
            "add_tag": dry_run_add_tag,
        }
        handler = handlers.get(tool)
        if handler is None:
            raise DryRunUnsupported(tool)
        return await handler(dict(args or {}))

    return dry_run
