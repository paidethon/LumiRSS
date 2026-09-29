"""NEW-265 翻译任务预算预估 —— 提交前基于真实配置与字数的估价。

预估是只读预检：绝不调用 provider、绝不写任何缓存行。

- 待翻文字量来自用户当前提交范围的实际块文本（normalize 后逐块
  计数，与生成路径同一 normalize），不是文章总量、更不是臆造数；
- 分块按生成路径的同一规则归类：
    no_translate（N086 标记）→ 永不发 provider，不计量；
    cached（成功缓存行命中）→ 已有结果不重复收费，不计量；
    revised（F062 人工修订保留）→ 默认不重发，不计量；
    chargeable → 其余将真实发 provider 的块；
- 费用估计基于用户自己登记的估算单价（每千字符 × 单价）。未登记
  单价 → estimatedCost=null + 诚实说明 —— 绝不臆造默认价，绝不
  伪造精确数字。估算是「字数近似」，不是计费账单。

全部 SQL 为内联字面量 + 绑定参数。
"""

from dataclasses import dataclass
from typing import Any

from lumirss.ai_settings import (
    KEY_TRANSLATION_ENGINE,
    KEY_TRANSLATION_LANGUAGE,
    TRANSLATION_ENGINE_BROWSER,
)
from lumirss.ai_translation_revisions import revision_map
from lumirss.ai_translation_segments import (
    SEGMENTS_PROMPT_VERSION,
    SegmentInput,
    block_hash,
    engine_identity,
    normalize_block_text,
)
from lumirss.entry_no_translate import marked_blocks
from lumirss.util import utc_now

BUDGET_ID = "budget"
MAX_BLOCKS = 64
MAX_NOTE = 120

_MAX_CHARS = 4000 * MAX_BLOCKS


class BudgetInvalid(Exception):
    """估价请求非法（空块 / 索引越界 / 非法单价）→ 422。"""


class BudgetEngineUnavailable(Exception):
    """当前引擎不由服务端翻译（browser）→ 预估诚实不可用。"""


_SETTINGS_SQL = "SELECT price_per_1k_chars, currency, updated_at FROM translation_budget_settings WHERE id = ?"

_UPSERT_SETTINGS_SQL = """INSERT INTO translation_budget_settings
(id, price_per_1k_chars, currency, updated_at)
VALUES (?, ?, ?, ?)
ON CONFLICT(id) DO UPDATE SET price_per_1k_chars = excluded.price_per_1k_chars,
currency = excluded.currency, updated_at = excluded.updated_at"""

_FETCH_SUCCESS_SQL = """SELECT block_index FROM ai_translation_segments
WHERE entry_ref = ? AND block_index = ? AND block_hash = ?
AND provider = ? AND model = ? AND prompt_version = ?
AND target_language = ? AND glossary_version = ? AND status = 'success'"""


@dataclass(frozen=True)
class BudgetSettings:
    price_per_1k_chars: float | None
    currency: str
    updated_at: str


@dataclass(frozen=True)
class BudgetEstimate:
    """一次只读预检的结果（估算，不是账单）。"""

    total_blocks: int
    chargeable_blocks: int
    cached_blocks: int
    no_translate_blocks: int
    revised_blocks: int
    total_chars: int
    chargeable_chars: int
    price_per_1k_chars: float | None
    currency: str
    estimated_cost: float | None
    engine: str
    note: str


async def get_budget_settings(db: Any) -> BudgetSettings:
    """每用户单行的估价参数（未登记 → price=None）。"""
    await db.migrate()
    row = await db.fetch_one(_SETTINGS_SQL, (BUDGET_ID,))
    if row is None:
        return BudgetSettings(None, "", "")
    price = row["price_per_1k_chars"]
    return BudgetSettings(
        price_per_1k_chars=float(price) if price is not None else None,
        currency=str(row["currency"] or ""),
        updated_at=str(row["updated_at"] or ""),
    )


async def save_budget_settings(
    db: Any,
    price_per_1k_chars: float | None,
    currency: str = "",
) -> BudgetSettings:
    """登记/清除（price=None）估算单价。价格必须是正数。"""
    await db.migrate()
    clean_currency = str(currency or "").strip()[:12]
    if price_per_1k_chars is not None:
        try:
            price = float(price_per_1k_chars)
        except (TypeError, ValueError) as exc:
            raise BudgetInvalid("单价必须是数字。") from exc
        if not price > 0:
            raise BudgetInvalid("单价必须大于 0。")
    else:
        price = None
    now = utc_now()
    await db.execute(
        _UPSERT_SETTINGS_SQL, (BUDGET_ID, price, clean_currency, now)
    )
    return BudgetSettings(price, clean_currency, now)


async def estimate(
    db: Any,
    settings: dict[str, str],
    blocks: list[SegmentInput],
    entry_ref: str = "",
) -> BudgetEstimate:
    """对用户即将提交的范围做只读预算预估。

    ``settings`` 是与生成路径同一来源的生效设置（调用方用
    SegmentTranslationService._resolve_settings() 解析）。
    ``entry_ref`` 提供时按该篇的缓存行/N086 标记/F062 修订归类；
    缺省时全部块视为待翻（新范围预检）。"""
    await db.migrate()
    clean: list[SegmentInput] = []
    seen: set[int] = set()
    total_chars = 0
    for block in blocks:
        if block.index in seen or block.index < 0 or block.index >= MAX_BLOCKS:
            raise BudgetInvalid("块索引重复或越界。")
        seen.add(block.index)
        text = normalize_block_text(block.text)
        if not text:
            continue
        total_chars += len(text)
        clean.append(SegmentInput(index=block.index, text=text))
    if not clean:
        raise BudgetInvalid("没有可预估的文本块。")
    if total_chars > _MAX_CHARS:
        raise BudgetInvalid("文本量超出可翻译范围。")

    engine = str(settings[KEY_TRANSLATION_ENGINE])
    if engine == TRANSLATION_ENGINE_BROWSER:
        raise BudgetEngineUnavailable(
            "浏览器翻译引擎由本机完成，服务端不翻译，也没有可预估的服务端费用。"
        )
    provider, model = engine_identity(engine, settings)
    language = settings[KEY_TRANSLATION_LANGUAGE]
    from lumirss.glossary import get_glossary_version

    glossary_version = await get_glossary_version(db)

    marks = await marked_blocks(db, entry_ref) if entry_ref else set()
    revisions = await revision_map(db, entry_ref) if entry_ref else {}

    chargeable_chars = 0
    cached = no_translate = revised = 0
    for block in clean:
        normalized = normalize_block_text(block.text)
        if entry_ref and block.index in marks:
            no_translate += 1
            continue
        if entry_ref and block.index in revisions:
            revised += 1
            continue
        if entry_ref:
            row = await db.fetch_one(
                _FETCH_SUCCESS_SQL,
                (
                    entry_ref,
                    block.index,
                    block_hash(normalized),
                    provider,
                    model,
                    SEGMENTS_PROMPT_VERSION,
                    language,
                    glossary_version,
                ),
            )
            if row is not None:
                cached += 1
                continue
        chargeable_chars += len(normalized)

    chargeable_blocks = len(clean) - cached - no_translate - revised
    budget = await get_budget_settings(db)
    if budget.price_per_1k_chars is None:
        estimated: float | None = None
        note = "未登记估算单价，无法估计费用；只统计了实际待翻字数。"
    elif chargeable_blocks == 0:
        estimated = 0.0
        note = "所选范围全部已有结果或被排除，本次提交预计零新增翻译。"
    else:
        estimated = round(chargeable_chars / 1000 * budget.price_per_1k_chars, 2)
        note = "按登记单价与实际待翻字数的近似估算，不是计费账单。"
    return BudgetEstimate(
        total_blocks=len(clean),
        chargeable_blocks=chargeable_blocks,
        cached_blocks=cached,
        no_translate_blocks=no_translate,
        revised_blocks=revised,
        total_chars=total_chars,
        chargeable_chars=chargeable_chars,
        price_per_1k_chars=budget.price_per_1k_chars,
        currency=budget.currency,
        estimated_cost=estimated,
        engine=engine,
        note=note,
    )
