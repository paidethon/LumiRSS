"""NEW-345 共享链接使用次数上限 —— 给指定链接设置使用上限；耗尽后
公开路由失效（410）；允许手动续额；每次访问留痕（含被拒的访问）。

- 判定是纯函数 ``evaluate_access``：revoked → not_found（对外 404，
  不泄露存在性）/ 耗尽 → limit_reached（410）/ 正常 → served；
- use_count 只在真实 served 时 +1；被拒访问不计数但照样留痕
  （result=limit_reached）——「耗尽后仍有人试图访问」是事实；
- 续额（topup）只加不上减：max_uses 与 use_count 保留，历史访问
  记录永不因续额清除 —— 撤不回已发生的外部访问，如实保留。

per-user：表在 per-user 库；B 看不到也无法续 A 的链接。
"""

from typing import Any

from lumirss.util import utc_now

MIN_MAX_USES = 1
MAX_MAX_USES = 100000
MIN_TOPUP = 1
MAX_TOPUP = 10000


class ShareLinkLimitInvalid(ValueError):
    """上限负载非法（映射 422）。"""


def clean_max_uses(raw: Any) -> int | None:
    """NULL = 不限上限；整数必须在 1..MAX_MAX_USES。"""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ShareLinkLimitInvalid("maxUses 必须是整数或 null（不限）。")
    if not MIN_MAX_USES <= raw <= MAX_MAX_USES:
        raise ShareLinkLimitInvalid(
            f"maxUses 必须在 {MIN_MAX_USES}..{MAX_MAX_USES} 之间。"
        )
    return raw


def clean_topup(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ShareLinkLimitInvalid("addUses 必须是整数。")
    if not MIN_TOPUP <= raw <= MAX_TOPUP:
        raise ShareLinkLimitInvalid(
            f"addUses 必须在 {MIN_TOPUP}..{MAX_TOPUP} 之间。"
        )
    return raw


def evaluate_access(link: dict[str, Any]) -> str:
    """纯函数判定：'not_found'（已撤销）/ 'limit_reached' / 'served'。"""
    if link.get("revokedAt") is not None:
        return "not_found"
    max_uses = link.get("maxUses")
    if max_uses is not None and int(link.get("useCount") or 0) >= int(max_uses):
        return "limit_reached"
    return "served"


async def record_access(
    db: Any, link_id: int, result: str, *, now: str | None = None
) -> None:
    """留痕一次访问（尽力而为）；served 时同时累加 use_count 并在
    首次达到上限时写 exhausted_at。"""
    moment = now or utc_now()
    try:
        await db.migrate()
        await db.execute(
            "INSERT INTO share_link_accesses (link_id, accessed_at, result)"
            " VALUES (?, ?, ?)",
            (link_id, moment, result),
        )
        if result == "served":
            row = await db.fetch_one(
                "SELECT max_uses, use_count FROM share_links WHERE id = ?",
                (link_id,),
            )
            if row is None:
                return
            new_count = int(row["use_count"]) + 1
            exhausted = (
                row["max_uses"] is not None
                and new_count >= int(row["max_uses"])
            )
            if exhausted:
                await db.execute(
                    "UPDATE share_links SET use_count = ?, exhausted_at ="
                    " COALESCE(exhausted_at, ?) WHERE id = ?",
                    (new_count, moment, link_id),
                )
            else:
                await db.execute(
                    "UPDATE share_links SET use_count = ? WHERE id = ?",
                    (new_count, link_id),
                )
    except Exception:  # noqa: BLE001 — 记账失败不阻塞响应
        return


async def topup(db: Any, link: dict[str, Any], add_uses: int) -> dict[str, Any]:
    """手动续额：max_uses += add（原 max_uses 为 NULL → 从当前
    use_count 起算），清 exhausted_at；历史记录保留。"""
    amount = clean_topup(add_uses)
    current_max = link.get("maxUses")
    base = int(current_max) if current_max is not None else int(
        link.get("useCount") or 0
    )
    new_max = base + amount
    if new_max > MAX_MAX_USES:
        raise ShareLinkLimitInvalid(f"续额后 maxUses 不能超过 {MAX_MAX_USES}。")
    await db.migrate()
    await db.execute(
        "UPDATE share_links SET max_uses = ?, exhausted_at = NULL WHERE id = ?",
        (new_max, int(link["id"])),
    )
    return {
        "id": int(link["id"]),
        "maxUses": new_max,
        "useCount": int(link.get("useCount") or 0),
        "added": amount,
        "note": "历史访问记录保留：续额不抹去已发生的外部访问。",
    }


async def list_accesses(
    db: Any, link_id: int, limit: int = 100
) -> list[dict[str, Any]]:
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT id, accessed_at, result FROM share_link_accesses"
        " WHERE link_id = ? ORDER BY id DESC LIMIT ?",
        (link_id, max(1, min(int(limit), 500))),
    )
    return [
        {
            "id": int(row["id"]),
            "accessedAt": str(row["accessed_at"]),
            "result": str(row["result"]),
        }
        for row in rows
    ]
