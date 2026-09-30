"""FIX-308 — AI 上下文截断不得把来源 ID 与正文错配。

日报材料行（_material_lines）以「[sN] 标题/来源/发布 + 正文」为不可拆
对应单元；总字符预算 _MAX_TOTAL_CHARS 耗尽时必须整单元丢弃。N176 聚簇
分支（同事件多来源合并一行）的旧行为：预算在簇中途耗尽时仍会追加该行，
行首 ``[s1,s2,s3]`` 列出簇内全部编号，而正文只含前缀成员的〔sN〕段——
出现「行首承诺了 ID、正文里没有对应内容」的错配形态。

修复语义（真修）：
- 行首 ID 列表必须精确等于该行实际携带正文的成员 ID（内容与出处一体）；
- 一个成员都没有可携带时整行丢弃（与单文档分支 break 语义一致）；
- 预算充足时输出与旧行为逐字节一致（N176 聚簇行形态不变）。

引用检查侧（parse_and_validate_output / parse_issue_output）：不在
s1..sN 内的编号一律 DigestOutputInvalid——错配后引用检查仍能检出。
"""

import pytest

from lumirss import gpt_digest
from lumirss.gpt_digest import (
    DigestOutputInvalid,
    _material_lines,
    parse_and_validate_output,
)

run = __import__("asyncio").run


def _doc(index: int, body: str) -> dict[str, str]:
    return {
        "title": f"标题{index}",
        "feedTitle": f"来源{index}",
        "publishedAt": "2026-01-01T00:00:00Z",
        "contentText": body,
        "url": f"https://example.com/{index}",
        "entryRef": f"rss:{index}",
    }


def _ids_of(line: str) -> list[str]:
    """从一行材料行的行首 ``[s1,s2]`` 提取承诺的 ID 列表。"""
    assert line.startswith("[")
    header = line[1 : line.index("]")]
    return [sid for sid in header.split(",") if sid]


def _present_ids(line: str) -> list[str]:
    """行内真正携带正文的成员（〔sN〕段标签）。"""
    import re

    return re.findall(r"〔(s\d+)〕", line)


MONO = "甲" * 40


def test_budget_cut_group_header_lists_only_present_ids(monkeypatch):
    """预算在簇中途耗尽：行首 ID 必须只含实际携带正文的成员。"""
    monkeypatch.setattr(gpt_digest, "_MAX_TOTAL_CHARS", 100)
    material = [_doc(1, MONO), _doc(2, MONO), _doc(3, MONO)]
    lines = _material_lines(material, groups=[[0, 1, 2]])
    # 预算 100 只够 2 个成员（2×40=80 ≤ 100，3×40=120 > 100）。
    assert len(lines) == 1
    header_ids = _ids_of(lines[0])
    present = _present_ids(lines[0])
    assert present, "截断行仍应携带至少一个成员的正文"
    assert header_ids == present, (
        "行首 ID 与正文错配：header 列出的编号必须与行内〔sN〕段一致"
    )


def test_budget_exhausted_group_line_dropped_when_no_member_fits(monkeypatch):
    """预算耗尽后无可携带成员：整行丢弃，绝不输出空壳 ID 行。"""
    monkeypatch.setattr(gpt_digest, "_MAX_TOTAL_CHARS", 40)
    material = [_doc(1, MONO), _doc(2, MONO)]
    lines = _material_lines(material, groups=[[0], [1]])
    # 第一行（40 字符）恰好纳入；第二行会使 total 超预算 → 整单元丢弃。
    assert len(lines) == 1
    assert _ids_of(lines[0]) == ["s1"]
    assert "s2" not in lines[0]


def test_single_doc_line_never_shows_id_without_body(monkeypatch):
    """单文档分支：预算越界整单元丢弃——ID 与正文永不分离（基线）。"""
    monkeypatch.setattr(gpt_digest, "_MAX_TOTAL_CHARS", 50)
    material = [_doc(1, MONO), _doc(2, MONO)]
    lines = _material_lines(material)
    assert [ _ids_of(line)[0] for line in lines ] == ["s1"]
    for line in lines:
        assert line.split("\n", 1)[1] != ""


def test_ample_budget_group_line_byte_identical_to_legacy():
    """预算充足（默认常量）：N176 聚簇行形态与旧行为逐字节一致。"""
    material = [_doc(1, "正文一"), _doc(2, "正文二")]
    grouped = _material_lines(material, groups=[[0, 1]])
    assert len(grouped) == 1
    line = grouped[0]
    assert line.startswith("[s1,s2] 同一事件的多来源报道：")
    assert "〔s1〕标题1" in line and "〔s2〕标题2" in line


def test_citation_check_detects_unknown_source_id():
    """引用检查：不在 s1..sN 内的编号 → DigestOutputInvalid（错配可检出）。"""
    output = {
        "title": "日报",
        "sections": [
            {
                "heading": "栏目",
                "items": [
                    {"summary": "总结", "sourceIds": ["s9"], "uncertainty": None}
                ],
            }
        ],
        "limitations": [],
    }
    import json

    with pytest.raises(DigestOutputInvalid):
        parse_and_validate_output(json.dumps(output, ensure_ascii=False), ["s1", "s2"])


def test_citation_check_accepts_only_issued_ids():
    """发出的编号可引用；未发出的编号（截断丢弃）引用仍被检查拦截的
    前提是其超出 s1..sN 集合——此处钉住有效集语义本身。"""
    import json

    output = {
        "title": "日报",
        "sections": [
            {
                "heading": "栏目",
                "items": [
                    {"summary": "总结", "sourceIds": ["s1"], "uncertainty": None}
                ],
            }
        ],
        "limitations": [],
    }
    parsed = parse_and_validate_output(json.dumps(output, ensure_ascii=False), ["s1"])
    assert parsed["sections"][0]["items"][0]["sourceIds"] == ["s1"]
