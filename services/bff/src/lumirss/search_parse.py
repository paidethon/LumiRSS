"""N142 自然语言转过滤条件 — rule-based query preprocessor (NO model).

Parses a raw search query for recognizable constructs — date phrases
(今天/昨天/本周/本月/去年/近 N 天/last N days/YYYY-MM-DD), source-name
prefixes (来源:xxx / source:xxx / site:xxx), negations (``-词``) and
quoted phrases — and converts them into the SAME structured filter dict
saved views persist in ``filters_json`` (see
:func:`lumirss.saved_search_store.normalize_filters`). Whatever is not
recognized stays as the free-text query AND is listed in
``unrecognized`` — parts are never silently dropped.

House rules:
- pure rule engine, no model calls, no I/O; the caller injects a
  ``resolve_source`` callback (DB lookup over ``search_feeds``) so this
  module stays unit-testable;
- an unresolvable source name is moved to ``unrecognized`` (honest),
  never invented into a filter;
- the first recognizable date phrase wins; later date phrases are left
  in the free text and listed as unrecognized (ambiguous ranges are not
  silently merged);
- ``from``/``to`` follow the search SQL semantics: ``published_at >= from``
  and ``published_at < to`` — day-phrase ranges therefore end at the
  EXCLUSIVE next day so the last day is included;
- exclude carries at most 2 terms and phrase a single value (existing
  server limits): overflow constructs stay in the free text and are
  listed in ``unrecognized``.
"""

import inspect
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

# 与 saved_search_store._FILTER_KEYS 同一白名单（本次只会产出其中
# from / to / phrase / exclude / feedRef 五个键）。
MAX_EXCLUDE_TERMS = 2

KIND_DATE = "date"
KIND_SOURCE = "source"
KIND_PHRASE = "phrase"
KIND_EXCLUDE = "exclude"

# 来源解析回调：纯函数（测试）或异步 DB 查询（router）皆可。
SourceResolver = Callable[[str], str | None | Awaitable[str | None]]


@dataclass
class ParsedQuery:
    """parse-query 结果：filters + 剩余自由词 + 未识别部分（诚实列出）。"""

    filters: dict[str, str] = field(default_factory=dict)
    remaining_text: str = ""
    unrecognized: list[str] = field(default_factory=list)
    recognized: list[dict[str, str]] = field(default_factory=list)


def _iso(day: date) -> str:
    return day.isoformat()


def _day_range(day: date) -> tuple[date, date]:
    """具体日期 → [当天 00:00, 次日 00:00)（to 为排他上界）。"""
    return day, day + timedelta(days=1)


# 日期短语模式（按声明顺序扫描；命名组 range = (from, to) 计算器）。
# today 由调用方注入，保证纯函数可测。
def _relative_range(kind: str, today: date) -> tuple[date, date] | None:
    monday = today - timedelta(days=today.weekday())
    if kind == "today":
        return today, today + timedelta(days=1)
    if kind == "yesterday":
        return today - timedelta(days=1), today
    if kind == "this_week":
        return monday, monday + timedelta(days=7)
    if kind == "last_week":
        return monday - timedelta(days=7), monday
    if kind == "this_month":
        start = today.replace(day=1)
        nxt = (start + timedelta(days=32)).replace(day=1)
        return start, nxt
    if kind == "last_month":
        this_start = today.replace(day=1)
        start = (this_start - timedelta(days=1)).replace(day=1)
        return start, this_start
    if kind == "this_year":
        return date(today.year, 1, 1), date(today.year + 1, 1, 1)
    if kind == "last_year":
        return date(today.year - 1, 1, 1), date(today.year, 1, 1)
    return None


_WORD_DATE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pattern), kind)
    for pattern, kind in [
        (r"今天|今日", "today"),
        (r"昨天|昨日", "yesterday"),
        (r"本周|这周|这一周", "this_week"),
        (r"上周|上一周", "last_week"),
        (r"本月|这个月|这个月份", "this_month"),
        (r"上月|上个月", "last_month"),
        (r"今年", "this_year"),
        (r"去年|上一年", "last_year"),
    ]
]
_LAST_N_DAYS = re.compile(
    r"(?:近|最近|过去)\s*(\d{1,3})\s*天|last\s+(\d{1,3})\s+days?\b",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}|\d{4}/\d{1,2}/\d{1,2}")
_QUOTED = re.compile(r'"([^"]{1,120})"|“([^”]{1,120})”')
_SOURCE = re.compile(r"(?:来源|source|site)[:：]\s*([^\s]{1,200})")
# 否定词：行首/空白后的 ``-`` + 非空白（首字符不得再是连字符，避免
# 把 "--" 或负号误吃；ISO 日期先于否定扫描并消费，故不受连字符干扰）。
_NEGATION = re.compile(r"(?:(?<=\s)|^)-([^\s\W-][^\s]{0,49})")


def _consume_date_phrase(
    text: str, start: int, today: date
) -> tuple[tuple[date, date], int, str] | None:
    """尝试在 text[start:] 识别一个日期短语。

    返回 ((from, to), 消费长度, 原文) 或 None。"""
    head = text[start:]

    match = _ISO_DATE.match(head)
    if match is not None:
        raw = match.group(0)
        normalized = raw.replace("/", "-")
        try:
            parts = [int(p) for p in normalized.split("-")]
            day = date(parts[0], parts[1], parts[2])
        except (ValueError, IndexError):
            return None
        return (*_day_range(day), len(raw), raw)

    for pattern, kind in _WORD_DATE_PATTERNS:
        match = pattern.match(head)
        if match is not None:
            rng = _relative_range(kind, today)
            assert rng is not None
            return (*rng, len(match.group(0)), match.group(0))

    match = _LAST_N_DAYS.match(head)
    if match is not None:
        n = int(match.group(1) or match.group(2))
        if 1 <= n <= 365:
            raw = match.group(0)
            return (
                today - timedelta(days=n - 1),
                today + timedelta(days=1),
                len(raw),
                raw,
            )
    return None


async def parse_query(
    query: str,
    *,
    today: date,
    resolve_source: SourceResolver | None = None,
) -> ParsedQuery:
    """把自然语言查询拆成 filters + 剩余自由词 + 未识别清单。

    ``resolve_source``：来源名/URL 片段 → feed_url；None 或返回 None =
    无法解析（该片段进入 unrecognized，绝不凭空造过滤条件）。同步
    回调与协程回调皆可（协程版供 router 走 DB 解析）。本函数无 I/O
    （除非回调自身发起），无模型调用。
    """

    async def _resolve(token: str) -> str | None:
        if resolve_source is None or not token:
            return None
        resolved = resolve_source(token)
        if inspect.isawaitable(resolved):
            return await resolved
        return resolved

    text = (query or "").strip()
    result = ParsedQuery()
    if not text:
        return result

    consumed: list[tuple[int, int]] = []

    def _free(start: int, end: int) -> str:
        """未被任何已消费区间覆盖的 [start, end) 段。"""
        piece_start = start
        pieces: list[str] = []
        for c_start, c_end in sorted(consumed):
            if c_end <= piece_start:
                continue
            if c_start >= end:
                break
            if c_start > piece_start:
                pieces.append(text[piece_start : min(c_start, end)])
            piece_start = max(piece_start, c_end)
        if piece_start < end:
            pieces.append(text[piece_start:end])
        return " ".join(p for p in pieces if p.strip())

    # -- 1. 引号精确短语（最多 1 个槽位；溢出片段不消费 → 留在自由词，
    #        由下方剩余词扫描诚实列入 unrecognized）--
    phrase_used = False
    for match in _QUOTED.finditer(text):
        phrase = (match.group(1) or match.group(2) or "").strip()
        if not phrase:
            continue
        if not phrase_used:
            phrase_used = True
            consumed.append(match.span())
            result.filters["phrase"] = phrase
            result.recognized.append(
                {"kind": KIND_PHRASE, "text": match.group(0)}
            )

    # -- 2. 日期短语（首个生效；后续日期短语不消费 → 留在自由词）--
    date_used = False
    scan = 0
    while scan < len(text):
        if any(s <= scan < e for s, e in consumed):
            scan += 1
            continue
        parsed = _consume_date_phrase(text, scan, today)
        if parsed is None:
            scan += 1
            continue
        start_d, end_d, length, raw = parsed
        if not date_used:
            date_used = True
            consumed.append((scan, scan + length))
            result.filters["from"] = _iso(start_d)
            result.filters["to"] = _iso(end_d)
            result.recognized.append({"kind": KIND_DATE, "text": raw})
        scan += length

    # -- 3. 来源前缀（解析成功 → filters.feedRef；失败 → 留在自由词，
    #        绝不凭空造过滤条件）--
    for match in _SOURCE.finditer(text):
        if any(s < match.end(1) and e > match.start(1) for s, e in consumed):
            continue
        token = match.group(1).strip().strip("\"“”")
        resolved = await _resolve(token)
        if resolved:
            consumed.append(match.span())
            result.filters["feedRef"] = resolved
            result.recognized.append(
                {"kind": KIND_SOURCE, "text": match.group(0)}
            )

    # -- 4. 否定词（exclude 最多 2 词；溢出不消费 → 留在自由词）--
    exclude_terms: list[str] = []
    for match in _NEGATION.finditer(text):
        if any(s < match.end(1) and e > match.start(1) for s, e in consumed):
            continue
        term = match.group(1).strip()
        if not term:
            continue
        if len(exclude_terms) < MAX_EXCLUDE_TERMS:
            exclude_terms.append(term)
            consumed.append(match.span())
            result.recognized.append(
                {"kind": KIND_EXCLUDE, "text": match.group(0)}
            )
    if exclude_terms:
        result.filters["exclude"] = " ".join(exclude_terms)

    # -- 5. 剩余自由词：未识别文本按序保留为查询，并逐词列入
    #        unrecognized（诚实不静默丢弃；单一事实来源，避免重复列出）--
    leftover = _free(0, len(text))
    result.remaining_text = re.sub(r"\s+", " ", leftover).strip()
    for word in result.remaining_text.split(" "):
        word = word.strip()
        if word:
            result.unrecognized.append(word)

    # 白名单顺序稳定输出（便于契约测试与 UI 渲染）。
    ordered: dict[str, str] = {}
    for key in ("feedRef", "from", "to", "phrase", "exclude"):
        if key in result.filters:
            ordered[key] = result.filters[key]
    result.filters = ordered
    return result
