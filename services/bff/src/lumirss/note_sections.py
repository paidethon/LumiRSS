"""N079 笔记与事实分栏 —— 类型化小节（纯逻辑：校验 + 标签渲染）。

笔记正文（content_md）仍是单一真源；分栏是附加结构：

.. code-block:: json

    {"facts": ["…"], "interpretation": ["…"], "toVerify": ["…"]}

- facts = 原文事实（能在原文中指认的陈述）；
- interpretation = 个人解读（读者自己的推断/评价）；
- toVerify = 待核实（疑点、需要查证的说法）。

AI 面的诚实约定：凡把笔记内容喂给模型的地方（搜索投影 body、
后续 prompt 组装），一律用 :func:`render_typed_sections` 渲染的
「[事实]/[个人解读]/[待核实]」标签逐条标注 —— 绝不把个人判断
表述为原文事实。渲染是纯函数：无 IO，可独立单测。
"""

from typing import Any

SECTION_KEYS = ("facts", "interpretation", "toVerify")

# AI/导出消费面的类型标签（稳定词表；改词会改变 prompt 表面，需同步测试）。
SECTION_LABELS = {
    "facts": "事实",
    "interpretation": "个人解读",
    "toVerify": "待核实",
}

MAX_SECTION_ITEMS = 50  # 每栏条数上限
MAX_ITEM_CHARS = 1000  # 单条字符上限


class NoteSectionsInvalid(ValueError):
    """分栏负载非法（键未知/条目非字符串/超限），映射 422。"""


def empty_sections() -> dict[str, list[str]]:
    return {key: [] for key in SECTION_KEYS}


def validate_sections(value: Any) -> dict[str, list[str]]:
    """校验并归一化分栏：未知键拒绝；缺省键补空；返回干净的深拷贝。"""
    if value is None:
        return empty_sections()
    if not isinstance(value, dict):
        raise NoteSectionsInvalid("sections 必须是对象。")
    unknown = set(value) - set(SECTION_KEYS)
    if unknown:
        raise NoteSectionsInvalid(f"sections 含未知键：{', '.join(sorted(map(str, unknown)))}。")
    cleaned: dict[str, list[str]] = {}
    for key in SECTION_KEYS:
        raw = value.get(key)
        if raw is None:
            cleaned[key] = []
            continue
        if not isinstance(raw, list):
            raise NoteSectionsInvalid(f"sections.{key} 必须是字符串数组。")
        if len(raw) > MAX_SECTION_ITEMS:
            raise NoteSectionsInvalid(f"sections.{key} 最多 {MAX_SECTION_ITEMS} 条。")
        items: list[str] = []
        for entry in raw:
            if not isinstance(entry, str):
                raise NoteSectionsInvalid(f"sections.{key} 的条目必须是字符串。")
            text = entry.strip()
            if text == "":
                continue  # 空条目丢弃（诚实归一化，不落空行）
            if len(text) > MAX_ITEM_CHARS:
                raise NoteSectionsInvalid(
                    f"sections.{key} 的单条过长（≤{MAX_ITEM_CHARS} 字符）。"
                )
            items.append(text)
        cleaned[key] = items
    return cleaned


def parse_sections(raw: Any) -> dict[str, list[str]]:
    """存储值（JSON 串或 NULL）→ 干净分栏；损坏数据诚实归一为空栏，
    绝不让一条坏行炸掉整张笔记列表。"""
    import json as _json

    if raw is None:
        return empty_sections()
    try:
        parsed = _json.loads(str(raw))
    except (_json.JSONDecodeError, TypeError):
        return empty_sections()
    try:
        return validate_sections(parsed)
    except NoteSectionsInvalid:
        return empty_sections()


def sections_is_empty(sections: dict[str, list[str]]) -> bool:
    return all(len(items) == 0 for items in sections.values())


def render_typed_sections(sections: dict[str, list[str]]) -> str:
    """分栏 → 带 [事实]/[个人解读]/[待核实] 标签的逐条文本。

    空栏不出现在输出里；全空 → ''（调用方按无分栏处理）。这是 AI
    消费面（搜索投影 body / prompt 组装）唯一允许的渲染方式——标签
    必须逐条在场，模型才能区分「原文说了什么」与「读者认为什么」。"""
    lines: list[str] = []
    for key in SECTION_KEYS:
        label = SECTION_LABELS[key]
        for item in sections.get(key, []):
            lines.append(f"[{label}] {item}")
    return "\n".join(lines)
