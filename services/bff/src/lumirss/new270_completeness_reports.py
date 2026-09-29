"""NEW-270 翻译完整性报告 —— 任务结束的逐段完整性台账。

按原文段落（client 分块）如实分类当前状态，而不是只给成功百分比：

- translated：有成功缓存行，或有人工修订（人工终稿视为完整）；
- failed：缓存行 status='failed'（无法翻译，可显式重试/补译）；
- skipped：N086 标记「不翻译」的块（有意保留原文）；
- missing：从未生成（连失败行都没有）。

两个显式动作：

- report：只读预检 + 保存快照（每篇上限 REPORT_CAP 条，超出淘汰
  最旧）—— 供回看「哪里缺、补了多少」；
- fill：只对 missing + failed 段执行补译（generate 的缓存语义保证
  translated/revised/skipped 段零 provider 调用，已有结果不动），
  记录本次 filled 段数。绝无自动补译 —— 都由用户显式触发。

全部 SQL 为内联字面量 + 绑定参数。
"""

import uuid
from typing import Any

from lumirss.ai_translation_segments import SegmentInput, SegmentTranslationService
from lumirss.util import utc_now

REPORT_CAP = 20

_INSERT_SQL = """INSERT INTO translation_completeness_reports
(id, entry_ref, total, translated, failed, missing, skipped, filled, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""

_LIST_SQL = """SELECT * FROM translation_completeness_reports
WHERE entry_ref = ? ORDER BY created_at DESC, id DESC LIMIT ?"""

_PRUNE_SQL = """DELETE FROM translation_completeness_reports WHERE entry_ref = ?
AND id NOT IN (
SELECT id FROM translation_completeness_reports WHERE entry_ref = ?
ORDER BY created_at DESC, id DESC LIMIT ?)"""


class CompletenessInvalid(Exception):
    """报告/补译请求非法（空块集合等）→ 422。"""


def classify(states) -> dict[str, Any]:
    """把段状态如实分成 translated/failed/missing/skipped（含索引清单）。"""
    translated: list[int] = []
    failed: list[int] = []
    missing: list[int] = []
    skipped: list[int] = []
    for state in states:
        if state.no_translate:
            skipped.append(state.index)
        elif state.user_revision or state.status == "success":
            translated.append(state.index)
        elif state.status == "failed":
            failed.append(state.index)
        else:
            missing.append(state.index)
    return {
        "total": len(states),
        "translated": sorted(translated),
        "failed": sorted(failed),
        "missing": sorted(missing),
        "skipped": sorted(skipped),
    }


async def build_report(
    db: Any,
    service: SegmentTranslationService,
    entry_ref: str,
    blocks: list[SegmentInput],
) -> dict[str, Any]:
    """只读完整性分类（lookup 路径，零 provider 调用、零写入）。"""
    await db.migrate()
    if not blocks:
        raise CompletenessInvalid("没有可供报告的文本块。")
    states = await service.lookup(entry_ref, blocks)
    return classify(states)


async def save_report(
    db: Any, entry_ref: str, counts: dict[str, Any], filled: int = 0
) -> dict[str, Any]:
    """保存一次快照（超出 REPORT_CAP 淘汰最旧）。"""
    await db.migrate()
    report_id = f"tcr-{uuid.uuid4().hex[:16]}"
    now = utc_now()
    await db.execute(
        _INSERT_SQL,
        (
            report_id,
            entry_ref,
            int(counts["total"]),
            len(counts["translated"]),
            len(counts["failed"]),
            len(counts["missing"]),
            len(counts["skipped"]),
            int(filled),
            now,
        ),
    )
    await db.execute(_PRUNE_SQL, (entry_ref, entry_ref, REPORT_CAP))
    return {
        "id": report_id,
        "entryRef": entry_ref,
        "total": int(counts["total"]),
        "translated": len(counts["translated"]),
        "failed": len(counts["failed"]),
        "missing": len(counts["missing"]),
        "skipped": len(counts["skipped"]),
        "translatedIndexes": counts["translated"],
        "failedIndexes": counts["failed"],
        "missingIndexes": counts["missing"],
        "skippedIndexes": counts["skipped"],
        "filled": int(filled),
        "createdAt": now,
    }


async def fill_missing(
    db: Any,
    service: SegmentTranslationService,
    entry_ref: str,
    blocks: list[SegmentInput],
) -> dict[str, Any]:
    """显式补译：只发 missing + failed 段（其余段零 provider 调用），
    返回补译后的新快照（filled = 本次补成功的段数）。"""
    await db.migrate()
    before = await build_report(db, service, entry_ref, blocks)
    states = await service.generate(entry_ref, blocks)
    after = classify(states)
    targets = set(before["missing"]) | set(before["failed"])
    filled = len(targets & set(after["translated"]))
    return await save_report(db, entry_ref, after, filled)


async def list_reports(db: Any, entry_ref: str, limit: int = 20) -> list[dict[str, Any]]:
    """某篇的报告历史（新→旧）。"""
    await db.migrate()
    rows = await db.fetch_all(_LIST_SQL, (entry_ref, max(1, min(limit, REPORT_CAP))))
    return [
        {
            "id": str(row["id"]),
            "entryRef": str(row["entry_ref"]),
            "total": int(row["total"]),
            "translated": int(row["translated"]),
            "failed": int(row["failed"]),
            "missing": int(row["missing"]),
            "skipped": int(row["skipped"]),
            "filled": int(row["filled"]),
            "createdAt": str(row["created_at"] or ""),
        }
        for row in rows
    ]
