"""NEW-390 迁移结果逐项对账 —— 导入后对照原清单展示新增、对应、失败
与丢失，用户逐条完成迁移确认。

口径：

- 对账单由分卷导入（NEW-389）自动创建（expected = 集清单条目，
  results = 逐条 added/matched/failed/missing），也可用其他导入的
  结果手动创建；
- missing = 在原清单中、但导入结果里完全没出现——单独列出，绝不与
  failed 混淆（一个是处理了但失败，一个是根本没到）；
- 确认逐条进行（confirm externalIds 列表）——没有一键全收：逐条
  确认就是「用户逐条完成迁移确认」的验收本体；pending 减到 0 →
  completed；
- 台账（new390_reconciliations）保存 expected / results / confirmed
  与 pending 计数。

per-user：对账单在 member 自己的库。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_VALID_STATUSES = ("added", "matched", "failed", "missing")


class ReconcileInvalid(ValueError):
    """对账请求非法（映射 400）。"""


class ReconcileNotFound(Exception):
    """对账单不存在（映射 404）。"""


async def create_reconciliation(
    db: Database,
    expected_item_ids: list[str],
    results: list[dict[str, Any]],
    *,
    source: str = "manual",
) -> dict[str, Any]:
    """原清单 + 逐条导入结果 → 对账单（含 missing 判定）。"""
    await db.migrate()
    expected = []
    for item_id in expected_item_ids:
        clean = str(item_id).strip()[:500]
        if clean and clean not in expected:
            expected.append(clean)
    if not expected:
        raise ReconcileInvalid("原清单不能为空。")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in results:
        external_id = str(result.get("externalId") or "").strip()[:500]
        record_id = str(result.get("recordId") or "").strip()[:500]
        status = str(result.get("status") or "")
        if status not in _VALID_STATUSES:
            status = "failed"
        detail = str(result.get("detail") or "")[:300]
        title = str(result.get("title") or "")[:300]
        rows.append(
            {
                "externalId": external_id,
                "recordId": record_id,
                "title": title,
                "status": status,
                "detail": detail,
            }
        )
        if external_id:
            seen.add(external_id)
        if record_id:
            seen.add(record_id)
    for item_id in expected:
        if item_id not in seen:
            rows.append(
                {
                    "externalId": item_id,
                    "title": "",
                    "status": "missing",
                    "detail": "在原清单中，但导入结果里没有出现。",
                }
            )
    reconciliation_id = f"recon-{_uuid.uuid4().hex[:12]}"
    await db.execute(
        "INSERT INTO new390_reconciliations"
        " (id, source, expected_json, results_json, confirmed_json, pending_count,"
        " created_at) VALUES (?, ?, ?, ?, '[]', ?, ?)",
        (
            reconciliation_id,
            str(source)[:100],
            json.dumps(expected, ensure_ascii=False),
            json.dumps(rows, ensure_ascii=False),
            len(rows),
            utc_now(),
        ),
    )
    return await get_reconciliation(db, reconciliation_id) or {}


async def get_reconciliation(db: Database, reconciliation_id: str) -> dict[str, Any] | None:
    await db.migrate()
    row = await db.fetch_one(
        "SELECT id, source, expected_json, results_json, confirmed_json,"
        " pending_count, created_at FROM new390_reconciliations WHERE id = ?",
        (reconciliation_id,),
    )
    if row is None:
        return None
    return _view(row)


async def list_reconciliations(db: Database) -> list[dict[str, Any]]:
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT id, source, expected_json, results_json, confirmed_json,"
        " pending_count, created_at FROM new390_reconciliations"
        " ORDER BY created_at DESC, id ASC LIMIT 100"
    )
    return [_view(row) for row in rows]


def _view(row: Any) -> dict[str, Any]:
    results = json.loads(str(row["results_json"]))
    confirmed = json.loads(str(row["confirmed_json"]))
    counts = {"added": 0, "matched": 0, "failed": 0, "missing": 0}
    for entry in results:
        status = entry.get("status")
        if status in counts:
            counts[status] += 1
    return {
        "id": str(row["id"]),
        "source": str(row["source"]),
        "expectedCount": len(json.loads(str(row["expected_json"]))),
        "results": results,
        "confirmed": confirmed,
        "pendingCount": int(row["pending_count"]),
        "status": "completed" if int(row["pending_count"]) == 0 else "open",
        "counts": counts,
        "createdAt": str(row["created_at"]),
    }


async def confirm_items(
    db: Database, reconciliation_id: str, external_ids: list[str]
) -> dict[str, Any]:
    """逐条确认——只接受对账单里真实存在的条目。"""
    await db.migrate()
    row = await db.fetch_one(
        "SELECT id, results_json, confirmed_json, pending_count, source,"
        " expected_json, created_at FROM new390_reconciliations WHERE id = ?",
        (reconciliation_id,),
    )
    if row is None:
        raise ReconcileNotFound("对账单不存在。")
    results = json.loads(str(row["results_json"]))
    confirmed: list[str] = json.loads(str(row["confirmed_json"]))
    known = {
        str(entry.get("externalId") or "")
        for entry in results
        if entry.get("externalId")
    }
    accepted = 0
    for item_id in external_ids:
        clean = str(item_id).strip()[:500]
        if clean and clean in known and clean not in confirmed:
            confirmed.append(clean)
            accepted += 1
    pending = len(results) - len(confirmed)
    await db.execute(
        "UPDATE new390_reconciliations SET confirmed_json = ?, pending_count = ?"
        " WHERE id = ?",
        (json.dumps(confirmed, ensure_ascii=False), max(pending, 0), reconciliation_id),
    )
    updated = await get_reconciliation(db, reconciliation_id)
    assert updated is not None
    updated["acceptedNow"] = accepted
    return updated
