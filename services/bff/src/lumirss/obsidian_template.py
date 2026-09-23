"""P16 导出模板 — 变量替换渲染（纯函数，无任何代码执行）。

导出到 Obsidian 的 Markdown 由用户模板 + 文章上下文拼装。模板只有
一种语法：``{{var}}``（两侧空白容忍）。渲染是【纯字符串替换】：
- 允许变量：title / url / source / date / content / annotations /
  published（单一事实源 :data:`ALLOWED_TEMPLATE_VARS`）；
- 未知变量（含 ``{{ foo bar }}``、``{{x.y}}``、``{{__import__}}`` 这类
  非法形状）→ 记入 ``unknown_vars`` 并从结果中移除 —— 绝不静默透传，
  也绝不求值（没有 eval / format / getattr，属性访问形似物只是字面
  文本被丢弃）；
- 缺失的标量字段（None / 空串）渲染为空（省略）；
- ``annotations`` 接收批注列表 → 渲染为引用 bullet 列表；空列表渲染
  为「（无标注）」占位 —— 诚实缺失，不冒充有内容。
"""

import re
from dataclasses import dataclass, field

DEFAULT_TEMPLATE = (
    "{{title}}\n\n> 摘自 LumiRSS: {{url}}\n\n{{content}}\n\n— {{source}} {{date}}"
)

ALLOWED_TEMPLATE_VARS: tuple[str, ...] = (
    "title",
    "url",
    "source",
    "date",
    "content",
    "annotations",
    "published",
)

NO_ANNOTATIONS_PLACEHOLDER = "（无标注）"

_MAX_TEMPLATE_LENGTH = 20000

# 合法变量名：字母/下划线开头，仅字母数字下划线（拒绝点号、括号等）。
_VAR_NAME_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
# 任意 {{...}} 形状（用于捕捉非法变量名的「形似变量」）。
_ANY_VAR_RE = re.compile(r"\{\{[^{}]*\}\}")


class TemplateTooLong(ValueError):
    """模板超过长度上限。"""


@dataclass(frozen=True)
class TemplateRenderResult:
    text: str
    unknown_vars: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unknown_vars


def _render_annotations(value) -> str:  # noqa: ANN001 — list of dicts or str
    """批注 bullet 列表；空 →「（无标注）」占位。"""
    if value is None:
        return NO_ANNOTATIONS_PLACEHOLDER
    if isinstance(value, str):
        return value
    items = []
    for annotation in value:
        if isinstance(annotation, dict):
            quote = str(annotation.get("quote") or "").strip()
            link = str(annotation.get("link") or "").strip()
            if link:
                line = f'- 「{quote}」([定位]({link}))' if quote else f"- ([定位]({link}))"
            else:
                line = f"- 「{quote}」" if quote else ""
            if line:
                items.append(line)
        elif str(annotation).strip():
            items.append(f"- {str(annotation).strip()}")
    return "\n".join(items) if items else NO_ANNOTATIONS_PLACEHOLDER


def render_template(template: str, context: dict) -> TemplateRenderResult:  # noqa: ANN001
    """Plain replace — the ONLY rendering mechanism (no evaluation).

    Single pass over the TEMPLATE text: every ``{{...}}`` token is either
    substituted (known var) or dropped-and-reported (unknown). Text
    between tokens — and substituted VALUES — are never re-scanned, so
    article content that happens to contain ``{{...}}`` passes through
    verbatim. Returns the rendered text plus every unknown/illegal
    variable name encountered (for UI validation display).
    """
    text = str(template or "")
    if len(text) > _MAX_TEMPLATE_LENGTH:
        raise TemplateTooLong(f"模板过长（≤{_MAX_TEMPLATE_LENGTH} 字符）。")

    unknown: list[str] = []
    parts: list[str] = []
    cursor = 0
    for match in _ANY_VAR_RE.finditer(text):
        parts.append(text[cursor : match.start()])
        cursor = match.end()
        raw = match.group(0)[2:-2].strip()
        name_match = _VAR_NAME_RE.fullmatch(match.group(0))
        if name_match is None:
            if raw:
                unknown.append(raw)
            continue  # 非法形状/未知变量：不透传，从结果移除
        name = name_match.group(1)
        if name not in ALLOWED_TEMPLATE_VARS:
            unknown.append(name)
            continue
        value = context.get(name)
        parts.append(
            _render_annotations(value)
            if name == "annotations"
            else ("" if value is None else str(value))
        )
    parts.append(text[cursor:])
    # 去重保序（同一未知变量出现多次只报一次）。
    return TemplateRenderResult(text="".join(parts), unknown_vars=list(dict.fromkeys(unknown)))


def validate_template(template: str) -> list[str]:
    """UI 校验入口：未知变量清单（无未知 = 合法）。"""
    return render_template(template, {}).unknown_vars
