"""P16 obsidian_template — 变量替换渲染：默认模板、CJK、缺失字段、
未知变量诚实上报、纯替换零执行。"""

import pytest

from lumirss.obsidian_template import (
    ALLOWED_TEMPLATE_VARS,
    DEFAULT_TEMPLATE,
    NO_ANNOTATIONS_PLACEHOLDER,
    TemplateTooLong,
    render_template,
    validate_template,
)

CONTEXT = {
    "title": "量子计算浅说",
    "url": "https://example.com/q",
    "source": "科学周刊",
    "date": "2026-09-23",
    "published": "2026-09-23T08:00:00Z",
    "content": "第一段。\n\n第二段。",
    "annotations": [
        {"quote": "关键一句", "link": "/reader?entry=e1.a&para=abcd1234-2"},
        {"quote": "", "link": ""},
    ],
}


def test_default_template_renders_expected_document():
    result = render_template(DEFAULT_TEMPLATE, CONTEXT)
    assert result.ok
    assert result.text.startswith("# 量子计算浅说") is False  # 模板本身无 # 前缀
    assert "量子计算浅说" in result.text
    assert "> 摘自 LumiRSS: https://example.com/q" in result.text
    assert "— 科学周刊 2026-09-23" in result.text
    assert "第一段。\n\n第二段。" in result.text


def test_cjk_content_passes_through_verbatim():
    result = render_template("{{title}}/{{source}}/{{content}}", CONTEXT)
    assert result.text == "量子计算浅说/科学周刊/第一段。\n\n第二段。"


def test_annotations_rendered_as_bullet_list_with_para_link():
    result = render_template("{{annotations}}", CONTEXT)
    lines = result.text.splitlines()
    assert lines[0] == "- 「关键一句」([定位](/reader?entry=e1.a&para=abcd1234-2))"
    # 空摘录的批注不产生空气泡
    assert len(lines) == 1


def test_missing_scalar_fields_omitted():
    result = render_template("[{{title}}][{{url}}][{{date}}]", {})
    assert result.text == "[][][]"


def test_missing_annotations_render_empty_placeholder():
    result = render_template("{{annotations}}", {})
    assert result.text == NO_ANNOTATIONS_PLACEHOLDER
    result2 = render_template("{{annotations}}", {"annotations": []})
    assert result2.text == NO_ANNOTATIONS_PLACEHOLDER


def test_unknown_var_reported_and_not_passed_through():
    result = render_template("{{title}} {{oops}}", CONTEXT)
    assert result.unknown_vars == ["oops"]
    assert "{{oops}}" not in result.text


def test_illegal_var_shapes_flagged_not_evaled():
    # 属性访问 / 调用形似物只是字面文本：不上报执行、不透传、仅报未知。
    result = render_template("{{content.__class__}} {{__import__}}", {})
    assert set(result.unknown_vars) == {"content.__class__", "__import__"}
    assert result.text == " "  # 两个未知被移除，仅剩模板里的空格
    assert "__class__" not in result.text
    assert "import" not in result.text


def test_no_execution_dunder_payload_never_evaluates():
    # 即使模板里埋了形似 Python 表达式的内容，渲染也只是字符串替换。
    evil = "{{ content.__class__.__mro__ }}"
    result = render_template(evil, CONTEXT)
    assert result.unknown_vars == ["content.__class__.__mro__"]
    assert "mro" not in result.text
    assert "type" not in result.text


def test_content_containing_braces_is_not_rescanned():
    # 正文里的 {{...}} 是数据不是模板 —— 原样保留，不二次替换、不误报。
    result = render_template("{{content}}", {"content": "模板形似 {{title}} 文本"})
    assert result.text == "模板形似 {{title}} 文本"
    assert result.unknown_vars == []


def test_all_documented_vars_allowed():
    assert set(ALLOWED_TEMPLATE_VARS) == {
        "title", "url", "source", "date", "content", "annotations", "published",
    }
    result = render_template(
        "{{title}}{{url}}{{source}}{{date}}{{content}}{{annotations}}{{published}}",
        CONTEXT,
    )
    assert result.ok


def test_whitespace_tolerant_and_repeated_unknown_deduped():
    result = render_template("{{ title }} {{ title }} {{ nope }} {{ nope }}", CONTEXT)
    assert result.text == "量子计算浅说 量子计算浅说  "
    assert result.unknown_vars == ["nope"]


def test_template_too_long_rejected():
    with pytest.raises(TemplateTooLong):
        render_template("x" * 20001, {})


def test_validate_template_lists_unknowns():
    assert validate_template("{{title}} {{bogus}}") == ["bogus"]
    assert validate_template(DEFAULT_TEMPLATE) == []
