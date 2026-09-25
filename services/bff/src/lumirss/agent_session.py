"""F094/F095/F098/F099 Agent 会话扩展 —— 范围锁定 / 搜索 / 工具权限 / 分支。

独立成文件：agent_store.py 的写站点已满，且本模块职责自成一体。

- scope_json：{"workspaceId"} 或 {"entryRefs":[...]}；NULL = 不锁定。
  服务端在工具执行处过滤（agent_tools 读取 registry.context），
  资料文本无法绕过；直接调用 rag/search 端点不受影响（会话级）。
- tool_policy_json：{"mode":"all"|"readonly","allowedTools":[...],
  "maxOpsPerTurn":1..50}；NULL = 默认 all。评估是纯函数
  evaluate_policy——执行前服务端拒绝（tool_denied），非 UI 隐藏。
- 搜索：LIKE 扫描（每线程 ≤200 条、总结果 ≤50）；已删会话因级联
  删除自然不出现；空查询 → SearchInvalid（422）。
- 分支：复制 [0..message_index] 可见上下文（≤40 条上限）；工具调用
  仅复制为 transcript 记录（绝不重新执行）；审批/副作用不复制；
  原会话不变；branch_of 记录来源。

写站点 3 处（settings UPDATE / 分支线程 INSERT / 分支消息批插）。
"""

import json
from typing import Any

from lumirss.agent_store import AgentStore, args_hash
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_BRANCH_MESSAGES = 40
_SEARCH_SCAN_PER_THREAD = 200
_SEARCH_TOTAL = 50
_MAX_SNIPPET = 160
_UNSET = object()

ALLOWED_TOOL_POLICY_MODES = ("all", "readonly")
MAX_OPS_PER_TURN_LIMIT = 50
# N165: per-thread budget bounds.
MAX_TOOL_CALLS_BUDGET_LIMIT = 200
MAX_TURNS_BUDGET_LIMIT = 100


class ThreadSettingsInvalid(ValueError):
    """会话设置非法（scope/tool_policy 结构），映射 422。"""


class SearchInvalid(ValueError):
    """搜索查询非法（空/过长），映射 422。"""


class BranchInvalid(ValueError):
    """分支请求非法（消息序号越界），映射 422。"""


def validate_budget(budget: Any) -> dict | None:
    """N165：线程级预算 {maxToolCalls, maxTurns}（键皆可缺省）。"""
    if budget is None:
        return None
    if not isinstance(budget, dict):
        raise ThreadSettingsInvalid("budget 必须是对象或 null。")
    unknown = set(budget) - {"maxToolCalls", "maxTurns"}
    if unknown:
        raise ThreadSettingsInvalid(f"budget 含未知键：{sorted(unknown)}")
    clean: dict[str, Any] = {}
    for key, limit in (
        ("maxToolCalls", MAX_TOOL_CALLS_BUDGET_LIMIT),
        ("maxTurns", MAX_TURNS_BUDGET_LIMIT),
    ):
        value = budget.get(key)
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            raise ThreadSettingsInvalid(f"{key} 必须是整数。")
        if not 1 <= value <= limit:
            raise ThreadSettingsInvalid(f"{key} 必须在 1–{limit}。")
        clean[key] = value
    return clean or None


def validate_scope(scope: Any) -> dict | None:
    if scope is None:
        return None
    if not isinstance(scope, dict):
        raise ThreadSettingsInvalid("scope 必须是对象或 null。")
    unknown = set(scope) - {"workspaceId", "entryRefs"}
    if unknown:
        raise ThreadSettingsInvalid(f"scope 含未知键：{sorted(unknown)}")
    if "workspaceId" in scope and "entryRefs" in scope:
        raise ThreadSettingsInvalid("scope 只能是 workspaceId 或 entryRefs 之一。")
    if "workspaceId" in scope:
        if not isinstance(scope["workspaceId"], str) or not scope["workspaceId"]:
            raise ThreadSettingsInvalid("scope.workspaceId 必须是非空字符串。")
        return {"workspaceId": scope["workspaceId"]}
    if "entryRefs" in scope:
        refs = scope["entryRefs"]
        if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
            raise ThreadSettingsInvalid("scope.entryRefs 必须是字符串列表。")
        return {"entryRefs": [r for r in refs if r][:200]}
    return None


def validate_tool_policy(policy: Any) -> dict | None:
    if policy is None:
        return None
    if not isinstance(policy, dict):
        raise ThreadSettingsInvalid("toolPolicy 必须是对象或 null。")
    unknown = set(policy) - {"mode", "allowedTools", "maxOpsPerTurn"}
    if unknown:
        raise ThreadSettingsInvalid(f"toolPolicy 含未知键：{sorted(unknown)}")
    clean: dict[str, Any] = {}
    mode = policy.get("mode")
    if mode is not None:
        if mode not in ALLOWED_TOOL_POLICY_MODES:
            raise ThreadSettingsInvalid("mode 必须是 all|readonly。")
        clean["mode"] = mode
    allowed = policy.get("allowedTools")
    if allowed is not None:
        if not isinstance(allowed, list) or not all(
            isinstance(t, str) for t in allowed
        ):
            raise ThreadSettingsInvalid("allowedTools 必须是字符串列表。")
        clean["allowedTools"] = list(dict.fromkeys(allowed))[:100]
    max_ops = policy.get("maxOpsPerTurn")
    if max_ops is not None:
        if not isinstance(max_ops, int) or isinstance(max_ops, bool):
            raise ThreadSettingsInvalid("maxOpsPerTurn 必须是整数。")
        if not 1 <= max_ops <= MAX_OPS_PER_TURN_LIMIT:
            raise ThreadSettingsInvalid(
                f"maxOpsPerTurn 必须在 1–{MAX_OPS_PER_TURN_LIMIT}。"
            )
        clean["maxOpsPerTurn"] = max_ops
    return clean or None


def evaluate_policy(policy: dict | None, tool: str, *, is_write: bool) -> str | None:
    """返回拒绝原因（tool_denied 的 reason），None = 允许。

    N163：readonly 优先于白名单——研究模式预设（readonly + 只读白名单）
    下，任何写工具都拒绝为 readonly_mode，绝不因白名单未列出而降级成
    语义较弱的 tool_not_allowed（写拦截的安全语义必须显式）。"""
    if not policy:
        return None
    mode = policy.get("mode") or "all"
    if is_write and mode == "readonly":
        return "readonly_mode"
    allowed = policy.get("allowedTools")
    if allowed is not None and tool not in allowed:
        return "tool_not_allowed"
    return None


class AgentSessionStore:
    def __init__(self, db: Database, agent_store: AgentStore) -> None:
        self._db = db
        self._threads = agent_store

    # -- F094/F098 设置 ------------------------------------------------------

    async def get_settings(self, thread_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, title, scope_json, tool_policy_json, budget_json, branch_of FROM agent_threads WHERE id = ?",
            (thread_id,),
        )
        if row is None:
            return {}

        def _load(raw: Any) -> Any:
            if not raw:
                return None
            try:
                return json.loads(str(raw))
            except json.JSONDecodeError:
                return None

        return {
            "id": str(row["id"]),
            "title": str(row["title"]),
            "scope": _load(row["scope_json"]),
            "toolPolicy": _load(row["tool_policy_json"]),
            "budget": _load(row["budget_json"]),
            "branchOf": row["branch_of"],
        }

    async def update_settings(
        self,
        thread_id: str,
        *,
        title: str | None = None,
        scope: Any = _UNSET,
        tool_policy: Any = _UNSET,
        budget: Any = _UNSET,
    ) -> dict[str, Any]:
        current = await self.get_settings(thread_id)
        if not current:
            raise KeyError(thread_id)
        new_scope = current["scope"] if scope is _UNSET else validate_scope(scope)
        new_policy = (
            current["toolPolicy"]
            if tool_policy is _UNSET
            else validate_tool_policy(tool_policy)
        )
        new_budget = current["budget"] if budget is _UNSET else validate_budget(budget)
        new_title = (
            str(title).strip()[:100] if title is not None else current["title"]
        )
        await self._db.execute(
            "UPDATE agent_threads SET title = ?, scope_json = ?, tool_policy_json = ?, budget_json = ? WHERE id = ?",
            (
                new_title,
                json.dumps(new_scope, ensure_ascii=False) if new_scope else None,
                json.dumps(new_policy, ensure_ascii=False) if new_policy else None,
                json.dumps(new_budget, ensure_ascii=False) if new_budget else None,
                thread_id,
            ),
        )
        return await self.get_settings(thread_id)

    # -- F095 会话搜索 -------------------------------------------------------

    async def search_messages(self, q: str) -> list[dict[str, Any]]:
        needle = (q or "").strip()
        if not needle:
            raise SearchInvalid("查询不能为空。")
        if len(needle) > 200:
            raise SearchInvalid("查询过长（≤200 字符）。")
        await self._db.migrate()
        like = f"%{needle.replace('%', chr(92) + '%').replace('_', chr(92) + '_')}%"
        thread_rows = await self._db.fetch_all(
            "SELECT id, title FROM agent_threads ORDER BY created_at DESC LIMIT 200"
        )
        results: list[dict[str, Any]] = []
        for thread_row in thread_rows:
            if len(results) >= _SEARCH_TOTAL:
                break
            rows = await self._db.fetch_all(
                "SELECT seq, role, content FROM agent_messages WHERE thread_id = ? AND content LIKE ? ESCAPE '\\' ORDER BY seq ASC LIMIT ?",
                (str(thread_row["id"]), like, _SEARCH_SCAN_PER_THREAD),
            )
            for row in rows:
                if len(results) >= _SEARCH_TOTAL:
                    break
                try:
                    content = json.loads(str(row["content"]))
                except json.JSONDecodeError:
                    continue
                text = str(content.get("text") or "")
                if needle not in text:
                    # JSON 序列化形态命中但用户文本未命中（如 toolCalls）。
                    continue
                position = text.find(needle)
                start = max(0, position - 40)
                snippet = text[start : start + _MAX_SNIPPET]
                results.append(
                    {
                        "threadId": str(thread_row["id"]),
                        "threadTitle": str(thread_row["title"]),
                        "messageIndex": int(row["seq"]),
                        "role": str(row["role"]),
                        "snippet": snippet,
                    }
                )
        return results

    # -- F099 分支 -----------------------------------------------------------

    async def branch_thread(self, thread_id: str, message_index: int) -> dict[str, Any]:
        source = await self.get_settings(thread_id)
        if not source:
            raise KeyError(thread_id)
        rows = await self._db.fetch_all(
            "SELECT seq, role, content, citations FROM agent_messages WHERE thread_id = ? AND seq <= ? AND seq > ? ORDER BY seq ASC",
            (thread_id, int(message_index), max(int(message_index) - _MAX_BRANCH_MESSAGES, 0)),
        )
        if not rows:
            raise BranchInvalid("分支点没有可复制的上下文。")
        truncated = int(message_index) - len(rows) > 0
        new_id = await self._threads_create_branch(thread_id)
        copied = 0
        for row in rows:
            role = str(row["role"])
            try:
                content = json.loads(str(row["content"]))
            except json.JSONDecodeError:
                continue
            if role == "approval":
                continue  # 审批不复制（副作用语义绝不迁移）
            if role == "assistant":
                content = dict(content)
                calls = content.pop("toolCalls", None)
                content.pop("streaming", None)
                if calls:
                    content["text"] = (
                        str(content.get("text") or "")
                        + f"\n（分支快照：此处原有 {len(calls)} 次工具调用，未复制、不会重新执行。）"
                    ).strip()
            elif role == "tool":
                # 工具结果仅复制为 transcript 记录（无 callId 配对——
                # 不会进入 provider 工具协议，也绝不重新执行）。
                content = {
                    "branchTranscript": True,
                    "name": content.get("name"),
                    "result": content.get("result") or content.get("error"),
                }
            await self._threads.append_message(
                new_id,
                role=role,
                content=content,
                citations=json.loads(str(row["citations"] or "[]")),
            )
            copied += 1
        if truncated:
            await self._threads.append_message(
                new_id,
                role="assistant",
                content={
                    "text": f"（分支快照：原会话前段超出 {_MAX_BRANCH_MESSAGES} 条上限，仅保留最近 {copied} 条。）",
                    "branchTruncated": True,
                },
            )
        return {
            "threadId": new_id,
            "branchOf": thread_id,
            "copiedMessages": copied,
            "truncated": truncated,
        }

    async def _threads_create_branch(self, source_thread_id: str) -> str:
        from lumirss.agent_store import _new_id

        new_id = _new_id()
        await self._db.execute(
            "INSERT INTO agent_threads (id, title, created_at, scope_json, tool_policy_json, branch_of) SELECT ?, title, ?, scope_json, tool_policy_json, ? FROM agent_threads WHERE id = ?",
            (new_id, utc_now(), source_thread_id, source_thread_id),
        )
        return new_id

    # -- F097 审批行（预演用）-------------------------------------------------

    async def get_approval_row(self, thread_id: str, approval_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, call_id, tool, args_json, args_hash, status, created_at FROM agent_approvals WHERE id = ? AND thread_id = ?",
            (approval_id, thread_id),
        )
        if row is None:
            return None
        args = json.loads(str(row["args_json"]))
        return {
            "approvalId": str(row["id"]),
            "callId": str(row["call_id"]),
            "tool": str(row["tool"]),
            "args": args,
            "status": str(row["status"]),
            "createdAt": str(row["created_at"]),
            "hashOk": args_hash(str(row["tool"]), args) == str(row["args_hash"]),
        }
