"""NEW-305 接入死信处理页 —— 无法解析的 webhook 事件的查看与重放。

- 死信展示的是**脱敏摘要**（顶层类型/键名与值类型/字节数），原始
  载荷只在服务端留存（≤64KB，超出截断并标记）供修正映射后重放；
  API 永不回显 payload_raw —— 未受控内容不出信任边界；
- 重放 = 用**当前**接收映射重跑同一条接入管线（ingest_fn 注入，
  即 NEW-303 的接收逻辑）：成功 → 死信标记 replayed；接收端报告
  duplicate/decided（事件早已成功纳入）→ 同样标记 replayed 但注明
  「已成功的副作用不重放」（webhook_inbox 的 (endpoint, event_id)
  唯一约束兜底，绝不产生第二条已接受记录）；仍失败 → 死信保持
  pending 并更新失败原因；
- 每用户死信有界（≤200 条，超出按最旧已重放→最旧优先清理）；
- per-user：死信在 per-user 库，A 的死信对 B 不可见。
"""

import json
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MAX_RAW_BYTES = 64 * 1024
_MAX_DEAD_LETTERS = 200
_SUMMARY_MAX_KEYS = 32


class DeadLetterNotFound(Exception):
    """No such dead letter (for this user)."""


def summarize_payload(raw_text: str) -> dict[str, Any]:
    """脱敏摘要：顶层类型 + 键名/值类型清单（≤32 键）+ 字节数。

    绝不包含任何字符串值 —— 摘要可安全展示。"""
    encoded = raw_text.encode("utf-8")
    summary: dict[str, Any] = {
        "bytes": len(encoded),
        "truncated": len(encoded) > MAX_RAW_BYTES,
    }
    try:
        value = json.loads(raw_text)
    except json.JSONDecodeError:
        summary["topLevelType"] = "invalid_json"
        return summary
    if isinstance(value, dict):
        summary["topLevelType"] = "object"
        keys = [
            {"name": str(key)[:120], "type": _value_type(value[key])}
            for key in list(value)[:_SUMMARY_MAX_KEYS]
        ]
        summary["keys"] = keys
    elif isinstance(value, list):
        summary["topLevelType"] = "array"
        summary["length"] = len(value)
    else:
        summary["topLevelType"] = type(value).__name__
    return summary


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


class DeadLetterStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        *,
        endpoint_uuid: str,
        event_id: str,
        reason: str,
        raw_text: str,
    ) -> int:
        """记录/更新一条 pending 死信（同事件已有 pending → 原地更新）。

        返回死信 id。原始载荷截断到 MAX_RAW_BYTES（截断态在摘要里
        如实标记）。"""
        await self._db.migrate()
        stored_raw = raw_text.encode("utf-8")[:MAX_RAW_BYTES].decode("utf-8", "replace")
        summary = summarize_payload(raw_text)
        now = utc_now()
        existing = await self._db.fetch_one(
            "SELECT id FROM webhook_dead_letters WHERE endpoint_uuid = ? AND event_id = ? AND status = 'pending'",
            (endpoint_uuid, event_id),
        )
        if existing is not None:
            await self._db.execute(
                "UPDATE webhook_dead_letters SET reason = ?, payload_summary = ?, payload_raw = ?, "
                "payload_digest = ?, failed_at = ? WHERE id = ?",
                (
                    reason[:300],
                    json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
                    stored_raw,
                    _digest(stored_raw),
                    now,
                    int(existing["id"]),
                ),
            )
            return int(existing["id"])
        cursor = await self._db.execute(
            "INSERT INTO webhook_dead_letters (endpoint_uuid, event_id, reason, payload_summary, "
            "payload_raw, payload_digest, status, failed_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (
                endpoint_uuid,
                event_id,
                reason[:300],
                json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
                stored_raw,
                _digest(stored_raw),
                now,
            ),
        )
        await self._prune()
        return int(cursor)

    async def get(self, dead_letter_id: int) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, endpoint_uuid, event_id, reason, payload_summary, payload_raw, "
            "payload_digest, status, failed_at, replayed_at FROM webhook_dead_letters WHERE id = ?",
            (dead_letter_id,),
        )
        return dict(row) if row is not None else None

    async def list_dead_letters(
        self, *, status: str | None = None
    ) -> list[dict[str, Any]]:
        """死信清单 —— **脱敏视图**：绝不包含 payload_raw。"""
        await self._db.migrate()
        if status in ("pending", "replayed"):
            rows = await self._db.fetch_all(
                "SELECT id, endpoint_uuid, event_id, reason, payload_summary, status, failed_at, "
                "replayed_at FROM webhook_dead_letters WHERE status = ? ORDER BY id DESC LIMIT ?",
                (status, _MAX_DEAD_LETTERS),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT id, endpoint_uuid, event_id, reason, payload_summary, status, failed_at, "
                "replayed_at FROM webhook_dead_letters ORDER BY id DESC LIMIT ?",
                (_MAX_DEAD_LETTERS,),
            )
        letters: list[dict[str, Any]] = []
        for row in rows:
            try:
                summary = json.loads(str(row["payload_summary"]))
            except json.JSONDecodeError:
                summary = {"topLevelType": "unknown"}
            letters.append(
                {
                    "id": int(row["id"]),
                    "endpointUuid": str(row["endpoint_uuid"]),
                    "eventId": str(row["event_id"]),
                    "reason": str(row["reason"]),
                    "payloadSummary": summary,
                    "status": str(row["status"]),
                    "failedAt": str(row["failed_at"]),
                    "replayedAt": row["replayed_at"],
                }
            )
        return letters

    async def mark_replayed(self, dead_letter_id: int) -> None:
        await self._db.execute(
            "UPDATE webhook_dead_letters SET status = 'replayed', replayed_at = ? WHERE id = ?",
            (utc_now(), dead_letter_id),
        )

    async def _prune(self) -> None:
        count_row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM webhook_dead_letters"
        )
        if count_row is None or int(count_row["n"]) <= _MAX_DEAD_LETTERS:
            return
        excess = int(count_row["n"]) - _MAX_DEAD_LETTERS
        # 先清最旧的已重放，再清最旧的 pending —— 有界诚实。
        await self._db.execute(
            "DELETE FROM webhook_dead_letters WHERE id IN ("
            "SELECT id FROM webhook_dead_letters WHERE status = 'replayed' "
            "ORDER BY id ASC LIMIT ?)",
            (excess,),
        )
        still = await self._db.fetch_one("SELECT COUNT(*) AS n FROM webhook_dead_letters")
        if still is not None and int(still["n"]) > _MAX_DEAD_LETTERS:
            await self._db.execute(
                "DELETE FROM webhook_dead_letters WHERE id IN ("
                "SELECT id FROM webhook_dead_letters ORDER BY id ASC LIMIT ?)",
                (int(still["n"]) - _MAX_DEAD_LETTERS,),
            )


def _digest(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
