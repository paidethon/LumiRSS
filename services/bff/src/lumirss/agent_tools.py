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


# N162：批量写入的 args 形态——``itemRefs``（列表）替代单个 ``itemRef``。
# 单次审批绑定整个 args（args_hash），因此批量预演 + 单次批准即可覆盖
# 整批；批准后执行路径逐对象落地（幂等语义与单对象一致）。
_BATCH_ARG_KEY = "itemRefs"
_BATCH_PREVIEW_SAMPLES = 10


def _batch_refs(args: dict) -> list[str] | None:
    """args 携带批量 ref 列表 → 清洗后的列表；单对象形态 → None。

    空列表/非字符串列表不算批量（走单对象路径，由单对象校验报错）。"""
    raw = args.get(_BATCH_ARG_KEY)
    if not isinstance(raw, list):
        return None
    refs = [str(r) for r in raw if isinstance(r, str) and r.strip()]
    return refs or None


def _batch_preview(
    target: str,
    per_object: list[dict],
    uncertain: list[str],
) -> dict:
    """N162：聚合预演卡片——单次批准覆盖整批。

    - perObjectDeltas 最多展示 10 个样本（如实标注截断）；
    - uncertainCount > 0 = 整批标记不确定（审批 UI 必须整批提示），
      但不改变批准语义（幂等重复仍可安全放行）。"""
    return {
        "target": target,
        "changes": [],
        "uncertain": list(uncertain),
        "batch": {
            "objectCount": len(per_object),
            "perObjectDeltas": per_object[:_BATCH_PREVIEW_SAMPLES],
            "perObjectTruncated": max(len(per_object) - _BATCH_PREVIEW_SAMPLES, 0),
            "uncertainCount": len(uncertain),
        },
    }


# N169: write tools with recorded before/after diffs and undo semantics.
# save_bookmark deliberately NOT included (a created library item is
# user data — undo would silently delete; unsupported → 422).
UNDOABLE_WRITE_TOOLS = frozenset({"add_to_workspace", "add_tag"})


def build_undo_support(**services):
    """N169 写工具撤销支持（与工具注册表同一服务装配）。

    - ``capture(tool, args, phase)``：写入执行前/后对目标对象做快照
      （workspace 成员行 / 标签绑定行），台账存档（差异撤销证据）；
    - ``undo(tool, args, before, after)``：按快照回滚。对象在写入之后
      又被修改过（位置/固定/分组/绑定来源变化，或已被移除）→
      UndoConflict（冲突报告，跳过）；不支持的工具 → UndoUnsupported。
    """
    workspaces = services["workspaces"]
    tags = services["tags"]

    async def _workspace_snapshot(args: dict) -> dict:
        workspace_id = str(args.get("workspaceId") or RESERVED_WORKSPACE_ID)
        raw_ref = str(args.get("itemRef") or "")
        try:
            item_ref = parse_item_ref(raw_ref).format()
        except ValueError:
            item_ref = raw_ref
        member = None
        if workspace_id:
            for item in await workspaces.list_items(workspace_id, limit=500):
                if item.item_ref == item_ref:
                    member = item
                    break
        return {
            "workspaceId": workspace_id,
            "itemRef": item_ref,
            "member": member is not None,
            "position": member.position if member is not None else None,
            "groupName": member.group_name if member is not None else None,
            "pinned": bool(member.pinned) if member is not None else None,
        }

    async def _tag_snapshot(args: dict) -> dict:
        raw_ref = str(args.get("itemRef") or "")
        name = str(args.get("name") or "")
        try:
            item_ref = parse_item_ref(raw_ref).format()
        except ValueError:
            item_ref = raw_ref
        binding = None
        for tag in await tags.tags_for_item(item_ref, include_suggested=True):
            if tag["name"].lower() == name.lower():
                binding = tag
                break
        return {
            "itemRef": item_ref,
            "name": name,
            "attached": binding is not None,
            "origin": str(binding["origin"]) if binding is not None else None,
        }

    async def capture(tool: str, args: dict, phase: str) -> dict | None:
        if tool not in UNDOABLE_WRITE_TOOLS:
            return None
        snapshot_args = dict(args or {})
        # N162：批量形态 → 逐对象快照（provenance 与单对象一致）。
        refs = _batch_refs(snapshot_args)
        if refs is not None:
            items = []
            for raw in refs:
                per_args = dict(snapshot_args)
                per_args.pop(_BATCH_ARG_KEY, None)
                per_args["itemRef"] = raw
                snapshot = (
                    await _workspace_snapshot(per_args)
                    if tool == "add_to_workspace"
                    else await _tag_snapshot(per_args)
                )
                items.append(snapshot)
            return {"phase": phase, "batch": True, "items": items}
        if tool == "add_to_workspace":
            snapshot = await _workspace_snapshot(snapshot_args)
        else:
            snapshot = await _tag_snapshot(snapshot_args)
        snapshot["phase"] = phase
        return snapshot

    async def undo(tool: str, args: dict, before: dict | None, after: dict | None) -> dict:
        if tool not in UNDOABLE_WRITE_TOOLS:
            from lumirss.agent_store import UndoUnsupported

            raise UndoUnsupported(f"工具 {tool} 不支持差异撤销。")
        if after is None:
            from lumirss.agent_store import UndoUnsupported

            raise UndoUnsupported("写入台账缺少撤销快照，无法撤销。")
        # N162：批量撤销 = 逐对象差异回滚；冲突对象如实报告并跳过。
        if before is not None and before.get("batch"):
            results = []
            for entry_before in before.get("items", []):
                per_args = dict(args or {})
                per_args.pop(_BATCH_ARG_KEY, None)
                per_args["itemRef"] = entry_before.get("itemRef")
                per_before = dict(entry_before)
                per_after = dict(after)
                per_after.pop("batch", None)
                per_after.pop("items", None)
                try:
                    if tool == "add_to_workspace":
                        outcome = await _undo_workspace(per_args, per_before, per_after)
                    else:
                        outcome = await _undo_tag(per_args, per_before, per_after)
                except Exception as exc:  # noqa: BLE001 — 单对象冲突不拦整批
                    outcome = {"undone": False, "conflictReason": str(exc)[:200]}
                results.append(outcome)
            return {
                "undone": all(r.get("undone") for r in results),
                "tool": tool,
                "batch": True,
                "results": results,
            }
        if tool == "add_to_workspace":
            return await _undo_workspace(args, before, after)
        return await _undo_tag(args, before, after)

    async def _undo_workspace(args: dict, before: dict | None, after: dict | None) -> dict:
        from lumirss.agent_store import UndoConflict

        current = await _workspace_snapshot(args)
        if not current["member"]:
            raise UndoConflict(
                "条目已不在目标工作区（写入后被移出），撤销跳过。"
            )
        if (
            current["position"] != after.get("position")
            or current["groupName"] != after.get("groupName")
            or current["pinned"] != after.get("pinned")
        ):
            raise UndoConflict(
                "工作区条目在写入后被修改过（位置/固定/分组），撤销跳过。"
            )
        await workspaces.remove_item(
            str(current["workspaceId"]), str(current["itemRef"])
        )
        return {
            "undone": True,
            "tool": "add_to_workspace",
            "workspaceId": current["workspaceId"],
            "itemRef": current["itemRef"],
        }

    async def _undo_tag(args: dict, before: dict | None, after: dict | None) -> dict:
        from lumirss.agent_store import UndoConflict

        current = await _tag_snapshot(args)
        if not current["attached"]:
            raise UndoConflict("标签绑定已不存在（写入后被移除），撤销跳过。")
        if current["origin"] != after.get("origin"):
            raise UndoConflict("标签绑定在写入后被修改过（来源变化），撤销跳过。")
        await tags.detach(str(current["itemRef"]), str(current["name"]))
        return {
            "undone": True,
            "tool": "add_tag",
            "itemRef": current["itemRef"],
            "name": current["name"],
        }

    return {"capture": capture, "undo": undo}


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
        refs = _batch_refs(args)
        if refs is not None:
            # N162：批量形态——单次批准覆盖整批（args_hash 绑定批量 args）。
            results = []
            for raw in refs:
                item = await workspaces.add_item(
                    workspace_id, parse_item_ref(raw).format()
                )
                results.append(
                    {"ref": item.item_ref, "position": item.position}
                )
            return {
                "added": True,
                "workspaceId": workspace_id,
                "objectCount": len(results),
                "results": results,
            }
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
        refs = _batch_refs(args)
        if refs is not None:
            # N162：批量形态——逐对象幂等落地，单次批准覆盖整批。
            name = str(args.get("name") or "")
            results = []
            for raw in refs:
                binding = await tag_store.attach(
                    parse_item_ref(raw).format(), name, origin="manual"
                )
                results.append(
                    {"ref": binding["ref"], "name": binding["name"]}
                )
            return {
                "tagged": True,
                "name": name,
                "objectCount": len(results),
                "results": results,
            }
        item_ref = parse_item_ref(str(args.get("itemRef") or "")).format()
        binding = await tag_store.attach(
            item_ref, str(args.get("name") or ""), origin="manual"
        )
        return {"tagged": True, "name": binding["name"], "ref": binding["ref"]}

    registry.register_write(
        "add_tag",
        "给一个条目（ItemRef）打一个手动标签；也可传 itemRefs 列表批量打标",
        {
            "type": "object",
            "properties": {
                "itemRef": {"type": "string"},
                "itemRefs": {"type": "array", "items": {"type": "string"}},
                "name": {"type": "string"},
            },
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
        refs = _batch_refs(args)
        if refs is not None:
            members = {
                item.item_ref for item in await workspaces.list_items(workspace_id, limit=500)
            }
            per = []
            uncertain = []
            for ref in refs:
                try:
                    item_ref = parse_item_ref(ref).format()
                except ValueError:
                    item_ref = ref
                already = item_ref in members
                per.append(
                    {
                        "ref": item_ref,
                        "changes": (
                            []
                            if already
                            else [{"field": "membership", "from": "absent", "to": item_ref}]
                        ),
                        "uncertain": [] if not already else ["条目已在工作区中（幂等重复）"],
                    }
                )
                if already:
                    uncertain.append(f"{item_ref}: 条目已在工作区中（幂等重复）")
            return _batch_preview(
                f"workspace:{workspace_id}（{summary.name}）", per, uncertain
            )
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
        refs = _batch_refs(args)
        if refs is not None:
            name = str(args.get("name") or "")
            per = []
            uncertain = []
            for raw in refs:
                try:
                    item_ref = parse_item_ref(raw).format()
                except ValueError:
                    item_ref = raw
                current = {t["name"] for t in await tags.tags_for_item(item_ref)}
                already = name in current
                per.append(
                    {
                        "ref": item_ref,
                        "changes": (
                            []
                            if already
                            else [{"field": "tag", "from": None, "to": name}]
                        ),
                        "uncertain": [] if not already else ["标签已存在（幂等）"],
                    }
                )
                if already:
                    uncertain.append(f"{item_ref}: 标签已存在（幂等）")
            return _batch_preview(f"tag:{name} × {len(per)}", per, uncertain)
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
