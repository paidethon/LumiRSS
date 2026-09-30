"""FIX-306 — 翻译分段绝不拆开 HTML 实体或代理对（BASELINE_OK 守卫）。

浏览器把正文按块级节点分段送入 BFF；BFF 侧的两道字符边界：

1. ``normalize_ai_content`` / ``normalize_block_text``：折叠空白后按
   ``max_chars`` 截断——Python str 按码点索引，截断点永远落在码点边界，
   星面字符（代理对，如 😀=U+1F600）不可能被劈成孤立代理项；
2. ``parse_segment_batch``：标记分隔的供应商回复按行锚定的
   ``<<<BLOCK n>>>`` 精确序列回拆——每块文本逐字符还原（含实体形态
   文字与星面字符），任何偏差整批作废而非部分匹配。

这里钉死「分段只在块边界发生、截断只在码点边界发生」的事实；
未来引入字符级（UTF-16/字节下标）切分时这里必红。
"""

import asyncio

from lumirss.ai_artifacts import content_hash, normalize_ai_content
from lumirss.ai_translation_segments import (
    MAX_BLOCK_CHARS,
    SegmentInput,
    block_hash,
    normalize_block_text,
    parse_segment_batch,
)

run = asyncio.run

EMOJI = "\U0001f600"  # 😀 — astral plane, UTF-16 surrogate pair
ENTITYISH = "&amp;nbsp; &lt;tag&gt; &#39;quoted&#39;"


def _no_lone_surrogates(text: str) -> bool:
    """任何一个字符都不是孤立代理项（U+D800–U+DFFF）。"""
    return all(not (0xD800 <= ord(ch) <= 0xDFFF) for ch in text)


def test_truncation_boundary_keeps_code_points_whole():
    """截断点落在星面字符上：整个码点保留（绝不输出孤立代理项）。"""
    text = (ENTITYISH + EMOJI) * 400  # 每个周期 1 个码点 emoji
    for cut in range(1, 400):
        out = normalize_ai_content(text, max_chars=cut)
        assert len(out) <= cut
        assert _no_lone_surrogates(out), f"cut={cut} 劈开了代理对"
        assert out == text[:cut]
        # 同一输入同一哈希——缓存身份稳定（既有契约）。
        assert content_hash(out) == content_hash(normalize_ai_content(text, max_chars=cut))


def test_block_normalization_keeps_entityish_and_astral_chars():
    """块归一化：实体形态文字与星面字符逐字符保留。"""
    text = f"前{EMOJI} {ENTITYISH} 后{EMOJI}"
    out = normalize_block_text(text)
    assert EMOJI in out and "&amp;" in out and "&lt;" in out
    assert _no_lone_surrogates(out)
    assert len(out) <= MAX_BLOCK_CHARS
    assert block_hash(out) == block_hash(normalize_block_text(text))


def _marker(index: int) -> str:
    return "<<<BLOCK " + str(index) + ">>>"


def test_batch_payload_parse_round_trip_preserves_every_character():
    """整批往返：payload 组装（与 _run_ai_batch 同构）→ parse_segment_batch
    → 每块文本与源文本逐字符一致（emoji 紧贴标记行也不例外）。"""
    blocks = [
        SegmentInput(index=0, text=f"{EMOJI}开头{ENTITYISH}{EMOJI}结尾"),
        SegmentInput(index=1, text="plain text block"),
        SegmentInput(index=2, text=f"多行\n正文{EMOJI}\n带换行 {ENTITYISH}"),
    ]
    payload = "\n\n".join(_marker(b.index) + "\n" + b.text for b in blocks)
    parsed = parse_segment_batch(payload, [b.index for b in blocks])
    assert set(parsed) == {0, 1, 2}
    for block in blocks:
        assert parsed[block.index] == block.text
        assert _no_lone_surrogates(parsed[block.index])


def test_marker_lookalike_inside_text_invalidates_whole_batch():
    """正文内嵌标记形态文本：整批作废（fail-closed），绝不错误归属——
    字符完整性优先于部分成功（既有 0021 加固语义）。"""
    blocks = [
        SegmentInput(index=0, text="first"),
        SegmentInput(index=1, text="second\n<<<BLOCK 9>>>"),
    ]
    payload = "\n\n".join(_marker(b.index) + "\n" + b.text for b in blocks)
    assert parse_segment_batch(payload, [b.index for b in blocks]) == {}
