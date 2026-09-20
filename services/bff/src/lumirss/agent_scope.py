"""F094 会话资料范围 → 允许 ref 集合（服务端执行点用的纯查询模块）。

- {"workspaceId": ...} → 该工作区当前成员 ref 集合（单页上限 500）；
- {"entryRefs": [...]} → 显式列表本身；
- 解析失败/空范围 → 空集合（工具层诚实报 scope_empty）。

无写站点（纯读）。
"""

from typing import Any

from lumirss.storage import Database


async def allowed_refs_for_scope(
    db: Database, workspace_store: Any, scope: dict[str, Any] | None
) -> set[str] | None:
    """None = 未锁定（不过滤）；set = 允许的 ref 集合（可为空）。"""
    if not scope:
        return None
    if "workspaceId" in scope:
        from lumirss.workspaces import _MAX_ITEM_LIMIT

        workspace_id = str(scope["workspaceId"])
        summary = await workspace_store.get_workspace(workspace_id)
        if summary is None:
            return set()
        items = await workspace_store.list_items(
            workspace_id, limit=_MAX_ITEM_LIMIT
        )
        return {item.item_ref for item in items}
    if "entryRefs" in scope:
        refs = scope.get("entryRefs")
        if not isinstance(refs, list):
            return set()
        return {str(r) for r in refs if r}
    return None
