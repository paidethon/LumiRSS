"""NEW-309 Webhook 投递回执 —— 逐次查看状态、重试计划与脱敏响应。

- 每次投递尝试一行：status success/failed、HTTP 状态码、脱敏响应
  摘要（文本 ≤300 字符，控制字符剥离；非文本只报字节数；请求头与
  签名永远不进回执）；
- 失败按固定退避计划重试（attempt ≤5：1/2/4/8/16 分钟封顶 60），
  next_retry_at 是重试计划的诚实呈现；
- 手动重试**复用同一 idempotency_key**（同一 (subscription, event)
  家族的所有尝试共享）—— 接收端凭该键安全去重，重放不会产生重复
  副作用；
- per-user：回执表在 per-user 库（RoutingDatabase），A 的投递历史
  对 B 完全不可见。

投递本身由 NEW-308 的 dispatch 执行（sender 可注入）；本模块拥有
回执的记录、脱敏、查询与重试调度。
"""

from typing import Any

from lumirss.util import utc_now

MAX_ATTEMPTS = 5
_BACKOFF_MINUTES = (1, 2, 4, 8, 16)
_MAX_BACKOFF_MINUTES = 60
_EXCERPT_CHARS = 300
_MAX_LIST = 100


class DeliveryNotFound(Exception):
    """No such delivery (for this user)."""


def sanitize_response_excerpt(content_type: str, body_text: str | None) -> str:
    """脱敏响应摘要：仅媒体类型族 + 有界文本（控制字符剥离）。

    响应头（可能含 Set-Cookie 等）与请求侧签名从不进入回执 —— 本
    函数的输入就已经只有 (content-type, body text)。"""
    family = (content_type or "").split(";")[0].strip().lower() or "unknown"
    if body_text is None:
        return f"[{family}] (无响应体)"
    cleaned = "".join(
        ch if ch.isprintable() or ch in "\t" else "\uFFFD" for ch in body_text
    )
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return f"[{family}] (空响应体)"
    excerpt = cleaned[:_EXCERPT_CHARS]
    if len(cleaned) > _EXCERPT_CHARS:
        excerpt += "…"
    return f"[{family}] {excerpt}"


def next_retry_at(attempt: int, *, now: str | None = None) -> str:
    """attempt 次失败后的下一次重试时刻（RFC3339）；超出计划 → ''。"""
    if attempt >= MAX_ATTEMPTS:
        return ""
    minutes = min(_BACKOFF_MINUTES[min(attempt, len(_BACKOFF_MINUTES)) - 1], _MAX_BACKOFF_MINUTES)
    from datetime import UTC, datetime, timedelta

    base = datetime.now(UTC)
    if now:
        base = datetime.fromisoformat(now.replace("Z", "+00:00"))
    return (base + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


class DeliveryStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def record_attempt(
        self,
        *,
        subscription_id: int,
        event_type: str,
        event_uuid: str,
        idempotency_key: str,
        attempt: int,
        ok: bool,
        response_status: int | None,
        response_excerpt: str | None,
    ) -> dict[str, Any]:
        """记录一次尝试；失败时排定下一次重试时刻（计划内）或终止。"""
        await self._db.migrate()
        now = utc_now()
        if ok:
            status, retry = "success", None
            finished = now
        else:
            retry = next_retry_at(attempt)
            status = "exhausted" if not retry else "failed"
            finished = now if not retry else None
        cursor = await self._db.execute(
            "INSERT INTO webhook_deliveries (subscription_id, event_type, event_uuid, "
            "idempotency_key, attempt, status, response_status, response_excerpt, "
            "next_retry_at, created_at, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                subscription_id,
                event_type,
                event_uuid,
                idempotency_key,
                attempt,
                status,
                response_status,
                response_excerpt,
                retry,
                now,
                finished,
            ),
        )
        return {
            "id": cursor,
            "attempt": attempt,
            "status": status,
            "responseStatus": response_status,
            "responseExcerpt": response_excerpt,
            "nextRetryAt": retry,
            "idempotencyKey": idempotency_key,
        }

    async def get(self, delivery_id: int) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, subscription_id, event_type, event_uuid, idempotency_key, attempt, "
            "status, response_status, response_excerpt, next_retry_at, created_at, finished_at "
            "FROM webhook_deliveries WHERE id = ?",
            (delivery_id,),
        )
        return dict(row) if row is not None else None

    async def last_attempt_for(
        self, subscription_id: int, event_uuid: str
    ) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT id, subscription_id, event_type, event_uuid, idempotency_key, attempt, "
            "status, response_status, response_excerpt, next_retry_at, created_at, finished_at "
            "FROM webhook_deliveries WHERE subscription_id = ? AND event_uuid = ? "
            "ORDER BY attempt DESC LIMIT 1",
            (subscription_id, event_uuid),
        )
        return dict(row) if row is not None else None

    async def list_deliveries(
        self, subscription_id: int | None = None
    ) -> list[dict[str, Any]]:
        await self._db.migrate()
        if subscription_id is None:
            rows = await self._db.fetch_all(
                "SELECT id, subscription_id, event_type, event_uuid, idempotency_key, attempt, "
                "status, response_status, response_excerpt, next_retry_at, created_at, finished_at "
                "FROM webhook_deliveries ORDER BY id DESC LIMIT ?",
                (_MAX_LIST,),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT id, subscription_id, event_type, event_uuid, idempotency_key, attempt, "
                "status, response_status, response_excerpt, next_retry_at, created_at, finished_at "
                "FROM webhook_deliveries WHERE subscription_id = ? ORDER BY id DESC LIMIT ?",
                (subscription_id, _MAX_LIST),
            )
        return [dict(row) for row in rows]

    async def due_deliveries(self, *, now_iso: str | None = None) -> list[dict[str, Any]]:
        """到点的失败投递（重试计划内）。"""
        await self._db.migrate()
        now = now_iso or utc_now()
        rows = await self._db.fetch_all(
            "SELECT id, subscription_id, event_type, event_uuid, idempotency_key, attempt, "
            "status, response_status, response_excerpt, next_retry_at, created_at, finished_at "
            "FROM webhook_deliveries WHERE status = 'failed' AND next_retry_at IS NOT NULL "
            "AND next_retry_at <= ? AND attempt < ? ORDER BY next_retry_at ASC LIMIT ?",
            (now, MAX_ATTEMPTS, _MAX_LIST),
        )
        return [dict(row) for row in rows]

    def to_dict(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "subscriptionId": int(row["subscription_id"]),
            "eventType": str(row["event_type"]),
            "eventUuid": str(row["event_uuid"]),
            "idempotencyKey": str(row["idempotency_key"]),
            "attempt": int(row["attempt"]),
            "status": str(row["status"]),
            "responseStatus": row["response_status"],
            "responseExcerpt": row["response_excerpt"],
            "nextRetryAt": row["next_retry_at"],
            "createdAt": str(row["created_at"]),
            "finishedAt": row["finished_at"],
        }
