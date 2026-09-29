"""NEW-271 AI 任务输入预览 —— 执行摘要/问答前展示将发送的确切范围。

诚实口径（与既有 F025 一脉相承）：

- 预览与真实发送共用同一套组装：问答用 ai_conversation 的
  build_conversation_parts / preview_inputs（标题/来源/缓存摘要/正文/
  用户笔记，历史与问题单独计数）；摘要用 ai_summary 的 _scope 同一
  截断规则——摘要提示只发送正文（含 maxChars 范围），不含标题/来源/
  笔记，预览如实说明，绝不虚报分段；
- 「可选笔记」是用户显式输入的文本（≤2000 字符），随问答请求一并
  发送时计入 section —— 服务端绝不假装能猜到用户想带什么；
- NEW-278 联动：exclude 中的分段在发送路径被真实剔除，预览从同一
  组装结果生成（所见即所发）；
- 预览绝不调用 provider，零费用；字符数不是 token（token 计数以
  Provider 为准）。

本模块无持久化：预览是活数据的即时快照（文章正文变化 → 下次预览
如实反映）——因此本项没有迁移表。
"""

from dataclasses import dataclass

from lumirss.ai_conversation import (
    _PART_LABELS,
    PART_BODY,
    PART_CACHED_SUMMARY,
    PART_FEED_TITLE,
    PART_NOTE,
    PART_TITLE,
    ConversationPreviewInputs,
)

SUMMARY_DEFAULT_CHARS = 12000
CONVERSATION_DEFAULT_CHARS = 8000
MAX_NOTE_CHARS = 2000

_PURPOSES = ("summary", "conversation")

_HONESTY_NOTE = "字符数非 token；token 计数以 Provider 为准。"
_SUMMARY_SCOPE_NOTE = "摘要提示只发送正文（受 maxChars 限制），不含标题/来源/笔记。"


class UnknownPreviewPurpose(ValueError):
    """purpose 不是 summary/conversation（422）。"""


@dataclass(frozen=True)
class InputSection:
    key: str
    label: str
    included: bool
    total_chars: int
    effective_chars: int


def _summary_sections(scoped: str, full: str) -> tuple[InputSection, ...]:
    return (
        InputSection(
            key=PART_BODY,
            label=_PART_LABELS[PART_BODY],
            included=bool(scoped),
            total_chars=len(full),
            effective_chars=len(scoped),
        ),
    )


def _conversation_sections(
    inputs: ConversationPreviewInputs,
) -> tuple[InputSection, ...]:
    """分段直接来自与发送共用的组装产物：included = 真的会发送；
    被排除（NEW-278）或为空的分段如实显示 0 字符。历史与问题虽不经
    build_conversation_parts 组装，但同样是真实输入，单独计数。"""
    parts = {key: len(text) for key, text in inputs.parts}
    sections: list[InputSection] = []
    for key in (PART_TITLE, PART_FEED_TITLE, PART_CACHED_SUMMARY, PART_BODY, PART_NOTE):
        chars = parts.get(key, 0)
        sections.append(
            InputSection(
                key=key,
                label=_PART_LABELS[key],
                included=chars > 0,
                total_chars=chars,
                effective_chars=chars,
            )
        )
    sections.append(
        InputSection(
            key="history",
            label="对话历史",
            included=inputs.history_chars > 0,
            total_chars=inputs.history_chars,
            effective_chars=inputs.history_chars,
        )
    )
    sections.append(
        InputSection(
            key="question",
            label="本次问题",
            included=bool(inputs.question),
            total_chars=len(inputs.question),
            effective_chars=len(inputs.question),
        )
    )
    return tuple(sections)


@dataclass(frozen=True)
class InputPreview:
    purpose: str
    title: str
    feed_title: str
    sections: tuple[InputSection, ...]
    effective_text: str
    note: str
    truncated: bool

    def to_json(self) -> dict[str, object]:
        total_effective = sum(
            section.effective_chars for section in self.sections if section.included
        )
        return {
            "purpose": self.purpose,
            "title": self.title,
            "feedTitle": self.feed_title,
            "sections": [
                {
                    "key": section.key,
                    "label": section.label,
                    "included": section.included,
                    "totalChars": section.total_chars,
                    "effectiveChars": section.effective_chars,
                }
                for section in self.sections
            ],
            # 确切将发送的正文范围（body 的有效文本）；笔记单独给出。
            "effectiveText": self.effective_text,
            "note": self.note,
            "noteChars": len(self.note),
            "truncated": self.truncated,
            "totalEffectiveChars": total_effective,
            "honestyNote": _SUMMARY_SCOPE_NOTE
            if self.purpose == "summary"
            else _HONESTY_NOTE,
        }


def build_summary_preview(*, content: str, max_chars: int | None) -> InputPreview:
    """摘要预览：与 ai_summary._scope 同一截断规则（正文-only 提示）。"""
    from lumirss.ai_artifacts import normalize_ai_content as normalize_content

    body = normalize_content(content)
    limit = max_chars if max_chars is not None else SUMMARY_DEFAULT_CHARS
    scoped = body[:limit]
    return InputPreview(
        purpose="summary",
        title="",
        feed_title="",
        sections=_summary_sections(scoped, body),
        effective_text=scoped,
        note="",
        truncated=len(scoped) < len(body),
    )


def build_conversation_preview(inputs: ConversationPreviewInputs) -> InputPreview:
    """问答预览：从与发送共用的组装产物生成分段。"""
    body_text = next(
        (text for key, text in inputs.parts if key == PART_BODY), ""
    )
    return InputPreview(
        purpose="conversation",
        title=inputs.title,
        feed_title=inputs.feed_title,
        sections=_conversation_sections(inputs),
        effective_text=body_text,
        note=inputs.note,
        truncated=inputs.truncated,
    )
