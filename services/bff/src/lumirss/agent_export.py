"""F096 Agent 会话导出 —— Markdown 报告（只读，纯函数构造）。

- 角色前缀轮次：round = 一个 user 消息开启（到最后一个 user 之前）；
  rounds 参数取最后 N 轮（1–20）；
- 工具调用行：名称 + 参数摘要（≤200 字）+ 状态（成功/失败/
  branchTranscript 快照标注）；
- 审批结论：approved / rejected / expired 如实标注；
- 机密剥离：args/输出中键名命中 password/token/secret/key 的值替换
  ***；形如 sk-… 的密钥串同样打码；
- 用户文本中的 Markdown 结构字符转义（行首 #/>/- 防注入 headings）；
- 空会话 → ExportInvalid（422）。

纯逻辑模块：无 SQL 站点（消息经 AgentStore 读取）。
"""

import json
import re
from typing import Any

from lumirss.agent_store import AgentStore

_MAX_ROUNDS = 20
_ARG_SUMMARY_LIMIT = 200

_SECRET_KEY_RE = re.compile(
    r"(password|passwd|token|secret|api[_-]?key|access[_-]?key|key)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(r"\b(sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S+)")


class ExportInvalid(ValueError):
    """导出请求非法（会话为空 / rounds 越界），映射 422。"""


def _redact(value: Any) -> Any:
    """递归脱敏：敏感键的值 → ***；密钥形态字符串打码。"""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for k, v in value.items():
            if _SECRET_KEY_RE.search(str(k)) and v not in (None, "", [], {}):
                cleaned[k] = "***"
            else:
                cleaned[k] = _redact(v)
        return cleaned
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, str):
        return _SECRET_VALUE_RE.sub("***", value)
    return value


def redact_json(value: Any) -> str:
    try:
        return json.dumps(_redact(value), ensure_ascii=False)
    except (TypeError, ValueError):
        return "«不可序列化»"


def escape_user_markdown(text: str) -> str:
    """用户文本防 Markdown 结构注入：行首结构字符转义；密钥形态串打码。"""
    text = _SECRET_VALUE_RE.sub("***", str(text or ""))
    lines = []
    for line in text.splitlines():
        if re.match(r"^\s{0,3}(#|>|-\s|\*\s|\d+\.\s|```)", line):
            lines.append("\\" + line)
        else:
            lines.append(line)
    return "\n".join(lines)


def _args_summary(args: Any) -> str:
    summary = redact_json(args if args is not None else {})
    if len(summary) > _ARG_SUMMARY_LIMIT:
        summary = summary[: _ARG_SUMMARY_LIMIT - 3] + "..."
    return summary


def build_export(
    thread: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    rounds: int,
) -> str:
    """渲染 Markdown 导出（纯函数；测试直接构造输入）。"""
    if not messages:
        raise ExportInvalid("会话为空，无可导出内容。")
    if not 1 <= int(rounds) <= _MAX_ROUNDS:
        raise ExportInvalid(f"rounds 必须在 1–{_MAX_ROUNDS}。")
    # 轮次切分：每个 user 消息开启一轮。
    round_starts = [
        index for index, m in enumerate(messages) if m["role"] == "user"
    ]
    if not round_starts:
        round_starts = [0]
    # rounds 超过实际轮数时取全部（不越界）。
    keep_from = round_starts[-min(int(rounds), len(round_starts))]
    kept = messages[keep_from:]

    lines = [
        f"# 会话导出：{thread.get('title') or '(未命名会话)'}",
        "",
        f"- 会话 id：{thread.get('id')}",
        f"- 导出轮数：{min(len(round_starts), int(rounds))}"
        f" / 全部 {len(round_starts)} 轮",
        "",
    ]
    round_number = sum(1 for start in round_starts if start < keep_from) + 1
    current_round = round_number
    for message in kept:
        role = message["role"]
        content = message.get("content") or {}
        if role == "user":
            lines.append(f"## 第 {current_round} 轮 · 用户")
            lines.append("")
            lines.append(escape_user_markdown(str(content.get("text") or "")))
            lines.append("")
            current_round += 1
        elif role == "assistant":
            text = str(content.get("text") or "")
            calls = content.get("toolCalls") or []
            if text:
                lines.append(f"### 第 {current_round - 1} 轮 · 助手")
                lines.append("")
                lines.append(text)
                lines.append("")
            for call in calls:
                lines.append(
                    f"- 工具调用 `{call.get('name')}` 参数：{_args_summary_safe(call)}"
                )
                lines.append("")
        elif role == "tool":
            name = str(content.get("name") or "")
            call_id = str(content.get("callId") or "")
            if content.get("branchTranscript"):
                lines.append(
                    f"- 工具结果（分支快照，未重新执行）`{name}`："
                    + _args_summary(content.get("result"))
                )
            elif content.get("error"):
                lines.append(
                    f"- 工具结果 `{name}`（call {call_id}）状态：**失败**"
                    f"（{content.get('error')}）"
                )
            else:
                lines.append(
                    f"- 工具结果 `{name}`（call {call_id}）状态：成功，输出："
                    + _args_summary(content.get("result"))
                )
            if content.get("approved"):
                lines.append("  - 审批结论：**approved**")
            lines.append("")
        elif role == "approval":
            status = str(content.get("status") or "unknown")
            lines.append(
                f"- 写操作审批 `{content.get('tool')}` 状态：**{status}**"
            )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _args_summary_safe(call: dict[str, Any]) -> str:
    raw = call.get("argumentsText")
    if raw:
        try:
            return _args_summary(json.loads(str(raw)))
        except (json.JSONDecodeError, TypeError):
            return _args_summary({"raw": str(raw)})
    return _args_summary({})


async def export_thread(
    store: AgentStore, thread_id: str, *, rounds: int
) -> tuple[dict[str, Any], str]:
    thread = await store.get_thread(thread_id)
    if thread is None:
        raise KeyError(thread_id)
    messages = await store.messages_after(thread_id, 0)
    return thread, build_export(thread, messages, rounds=rounds)
