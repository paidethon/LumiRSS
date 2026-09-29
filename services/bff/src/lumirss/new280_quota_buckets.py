"""NEW-280 AI 配额分桶 —— 用户把可用额度分到翻译/摘要/问答等用途。

- 行存在 = 该用途有分桶上限（每窗口调用数，应用层在配额守卫里
  原子预占，复用 ai_quota.claim_ai_call，键 "bucket:{purpose}:{窗口}"）；
  无行 = 未分桶 → 只走全局配额；
- 超额 → 429 带 scope="bucket" + purpose + 现状（调整入口），绝不
  静默超额；嵌套预占不回退（保守多计，与既有口径一致）；
- 快照如实给出每桶 used/remaining/nearLimit（≥80% 提示接近限额，
  用户选择调整而不是被静默截断）。

per-user：计数在 per-user 库的 ai_usage（RoutingDatabase），A 的用量
对 B 不可见。
"""

from typing import Any

from lumirss.ai_profiles import PURPOSES
from lumirss.ai_quota import window_bounds
from lumirss.storage import Database

MAX_BUCKET_CALLS = 100000
_NEAR_LIMIT_RATIO = 0.8


class BucketInvalid(ValueError):
    """分桶负载非法（映射 422）。"""


class BucketPurposeInvalid(BucketInvalid):
    """purpose 不在用途词表内。"""


def clean_purpose(purpose: str) -> str:
    if purpose not in PURPOSES:
        raise BucketPurposeInvalid(
            f"purpose 必须是 {'、'.join(PURPOSES)} 之一。"
        )
    return purpose


def _clean_max_calls(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise BucketInvalid("maxCalls 必须是整数。")
    if not 1 <= raw <= MAX_BUCKET_CALLS:
        raise BucketInvalid(f"maxCalls 必须在 1..{MAX_BUCKET_CALLS} 之间。")
    return raw


class QuotaBucketStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def set_bucket(self, purpose: str, max_calls: Any) -> dict[str, Any]:
        clean = clean_purpose(purpose)
        limit = _clean_max_calls(max_calls)
        await self._db.migrate()
        from lumirss.util import utc_now

        await self._db.execute(
            "INSERT INTO ai_quota_buckets (purpose, max_calls, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(purpose) DO UPDATE SET max_calls = excluded.max_calls, "
            "updated_at = excluded.updated_at",
            (clean, limit, utc_now()),
        )
        return {"purpose": clean, "maxCalls": limit}

    async def delete_bucket(self, purpose: str) -> bool:
        clean = clean_purpose(purpose)
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT purpose FROM ai_quota_buckets WHERE purpose = ?", (clean,)
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM ai_quota_buckets WHERE purpose = ?", (clean,)
        )
        return True

    async def snapshot(self, window: str) -> dict[str, Any]:
        """全部分桶 + 用量现状（used 来自 ai_usage 的分桶键）。"""
        await self._db.migrate()
        bounds = window_bounds(window=window)
        rows = await self._db.fetch_all(
            "SELECT purpose, max_calls, updated_at FROM ai_quota_buckets "
            "ORDER BY purpose ASC"
        )
        buckets: list[dict[str, Any]] = []
        for row in rows:
            purpose = str(row["purpose"])
            if purpose not in PURPOSES:
                continue  # 未知用途行不进快照（诚实：不假装是有效桶）
            bucket_key = f"bucket:{purpose}:{bounds.key}"
            usage = await self._db.fetch_one(
                "SELECT calls FROM ai_usage WHERE window_key = ?", (bucket_key,)
            )
            used = int(usage["calls"]) if usage is not None else 0
            max_calls = int(row["max_calls"])
            buckets.append(
                {
                    "purpose": purpose,
                    "maxCalls": max_calls,
                    "used": used,
                    "remaining": max(0, max_calls - used),
                    "nearLimit": used >= max_calls * _NEAR_LIMIT_RATIO,
                    "updatedAt": str(row["updated_at"]),
                }
            )
        return {
            "window": window,
            "windowKey": bounds.key,
            "windowReset": bounds.reset_iso,
            "buckets": buckets,
            "purposes": list(PURPOSES),
            "honestyNote": (
                "分桶是每窗口调用数上限（预占即计数，失败不回退）；"
                "接近限额时请调整分桶，系统不会静默超额。"
            ),
        }
