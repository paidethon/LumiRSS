"""N082 翻译数字校验 —— 纯后验的「可见数字差异」比对（非语义判断）。

诚实边界（UI 文案同口径）：

- 只提取并比较阿拉伯数字 token：整数、小数、千分位逗号形式
  （``3,500`` / ``1,234.56``）与可选 ``%`` 后缀；
- CJK 数字（一/二/三/两…）明确不在范围内 —— 不提取、不比较；
- 因此本功能回答的是「哪些可见数字在译文里缺失/被改动/多出来了」，
  绝不判断语义或翻译质量；差异也不必然是错误（如单位换算、货币
  格式本地化），最终判断留给读者。

比对 = 源文/译文 token 多重集之差：

- ``missing``：源文有、译文无；
- ``added``：译文有、源文无；
- ``changed``：未配对的 missing/added token 两两 Levenshtein 距离
  ≤ 1（如 ``50%``→``60%`` 的单字符漂移、``3,500``→``350`` 的失位）
  合并为一条 changed，剩余的各自按 missing/added 报告。

每条附带 ≤40 字符的源/译上下文（token 两侧窗口，纯文本切片）；
总条数上限 10（MAX_FINDINGS），超出即截断 —— 校验是提示，不是报告。
"""

import re
from collections import Counter

MAX_FINDINGS = 10
_CONTEXT_CHARS = 40
_MAX_EDIT_DISTANCE = 1

# 千分位形式优先（否则 "3,500" 会被拆成 "3" 和 "500"）。
_NUMBER_TOKEN_RE = re.compile(
    r"\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|\d+(?:\.\d+)?%?"
)


def extract_number_tokens(text: str) -> list[str]:
    """按出现顺序提取数字 token（含 % 与千分位；CJK 数字不提取）。"""
    if not text:
        return []
    return _NUMBER_TOKEN_RE.findall(text)


def _context(text: str, token: str) -> str:
    """token 首次出现位置的 ≤40 字符纯文本窗口（找不到 → 空串）。"""
    if not text:
        return ""
    pos = text.find(token)
    if pos == -1:
        return ""
    start = max(0, pos - 12)
    return text[start : start + _CONTEXT_CHARS]


def _levenshtein_within(a: str, b: str, limit: int) -> bool:
    """短 token（数字串）的双行 Levenshtein；只回答 ≤limit 与否。"""
    if abs(len(a) - len(b)) > limit:
        return False
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (ca != cb),
                )
            )
        if min(current) > limit:
            return False
        previous = current
    return min(previous) <= limit


def verify_numbers(source_text: str, translated_text: str) -> list[dict[str, str]]:
    """比较源/译数字 token 多重集；返回 ≤10 条差异（kind/token/上下文）。"""
    source_counts = Counter(extract_number_tokens(source_text))
    translated_counts = Counter(extract_number_tokens(translated_text))
    missing = list((source_counts - translated_counts).elements())
    added = list((translated_counts - source_counts).elements())

    findings: list[dict[str, str]] = []
    added_used = [False] * len(added)
    remaining_missing: list[str] = []
    for token in missing:
        paired = -1
        for i, candidate in enumerate(added):
            if added_used[i]:
                continue
            if _levenshtein_within(candidate, token, _MAX_EDIT_DISTANCE):
                paired = i
                break
        if paired == -1:
            remaining_missing.append(token)
            continue
        added_used[paired] = True
        findings.append(
            {
                "kind": "changed",
                "token": token,
                "sourceContext": _context(source_text, token),
                "translatedContext": _context(translated_text, added[paired]),
            }
        )
    for token in remaining_missing:
        findings.append(
            {
                "kind": "missing",
                "token": token,
                "sourceContext": _context(source_text, token),
                "translatedContext": "",
            }
        )
    for i, token in enumerate(added):
        if added_used[i]:
            continue
        findings.append(
            {
                "kind": "added",
                "token": token,
                "sourceContext": "",
                "translatedContext": _context(translated_text, token),
            }
        )
    return findings[:MAX_FINDINGS]
