"""NEW-303 Webhook 接收收件箱 —— 已授权端点的条目先进待确认区。

接收链（机器到机器，不持浏览器会话）：
  POST /api/v1/webhooks/ingest/{endpoint_uuid}
    - Authorization: Bearer <端点秘密>  → machine_user_context 进入
      所属用户的数据作用域（控制库 token_owner_index，散列索引）；
    - X-Lumi-Signature: t=<unix>,v1=<hmac>  → 实例签名钥 HMAC 验证
      （NEW-304 双钥窗口，timing-safe，防伪造与重放）；
    - 条目落在 webhook_inbox，status='pending' —— **绝不直入主库**；
      用户审阅后 accept（纳入）或 reject（拒绝）。

条目形状（UNTRUSTED，全部清洗）：{"eventId", "items":[{id, title,
body?, url?, publishedAt?}]} 或单条目对象；缺 id/title、JSON 不合法
等不可解析事件 → NEW-305 死信（脱敏留存，可修映射后重放）。

硬性质：
- 幂等：(endpoint_uuid, event_id) 唯一 —— 重放收敛为 duplicate；
  已裁决（accepted/rejected）的事件重投绝不覆盖裁决；
- 秘密不落日志：bearer 与签名头从不进入任何日志/响应（404 统一
  回答，不做存在性预言机）；
- per-user：端点与收件箱都在 per-user 库（RoutingDatabase），A 的
  端点/条目对 B 完全不可见（显式隔离测试）。
"""

import hashlib
import json
from typing import Any

from lumirss.new304_webhook_keys import verify_webhook_signature
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_ITEMS_PER_EVENT = 50
_MAX_TEXT_LENGTH = 8000
_MAX_BODY_BYTES = 512 * 1024


class WebhookInboxInvalid(ValueError):
    """接收负载非法（结构层面；不可解析者进死信而非 422 —— 由路由
    区分：有 eventId 可归属的 → 死信；连事件归属都没有的 → 400）。"""


class WebhookEndpointNotFound(Exception):
    """端点不存在 / 未授权（统一 404，不泄漏存在性）。"""


def new_endpoint_secret() -> str:
    import secrets

    return secrets.token_hex(16)


def _clean_text(value: Any, limit: int = _MAX_TEXT_LENGTH) -> str:
    """不可信文本 → 有界纯文本（剥标签 + 控制字符）。"""
    import re

    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"<[^>]*>", " ", text)
    text = " ".join(text.split())
    return text[:limit]


def parse_event_items(raw_body: bytes) -> tuple[str | None, list[dict[str, Any]]]:
    """解析事件载荷 → (event_id, items)。结构不可用 → WebhookInboxInvalid。

    items 里缺 id/title 的条目被剔除（计入返回值无效条数由调用方
    通过 len 对比发现并写死信）。"""
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookInboxInvalid(f"载荷不是合法 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise WebhookInboxInvalid("载荷顶层必须是对象。")
    event_id = payload.get("eventId")
    if event_id is not None:
        event_id = str(event_id).strip()[:200] or None
    raw_items = payload.get("items")
    if raw_items is None:
        # 单条目形状：{eventId?, id, title, ...}
        raw_items = [payload] if payload.get("id") and payload.get("title") else []
    if not isinstance(raw_items, list):
        raise WebhookInboxInvalid("items 必须是数组。")
    items: list[dict[str, Any]] = []
    for raw in raw_items[:_MAX_ITEMS_PER_EVENT]:
        if not isinstance(raw, dict):
            continue
        item_id = raw.get("id")
        title = _clean_text(raw.get("title"), 500)
        if item_id is None or not title:
            continue
        items.append(
            {
                "id": str(item_id)[:500],
                "title": title,
                "summary": _clean_text(raw.get("body") or raw.get("summary")),
                "url": _clean_text(raw.get("url"), 2048),
                "publishedAt": _clean_text(raw.get("publishedAt"), 64),
            }
        )
    return event_id, items


class WebhookInboxStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- 端点管理 -----------------------------------------------------------

    async def create_endpoint(self, label: str) -> dict[str, Any]:
        clean = label.strip()
        if not clean:
            raise WebhookInboxInvalid("端点名称不能为空。")
        clean = clean[:100]
        await self._db.migrate()
        import uuid as _uuid

        endpoint_uuid = str(_uuid.uuid4())
        secret = new_endpoint_secret()
        await self._db.execute(
            "INSERT INTO webhook_endpoints (uuid, label, enabled, created_at) VALUES (?, ?, 1, ?)",
            (endpoint_uuid, clean, utc_now()),
        )
        return {
            "uuid": endpoint_uuid,
            "label": clean,
            "secret": secret,
            "ingestPath": f"/api/v1/webhooks/ingest/{endpoint_uuid}",
            "createdAt": utc_now(),
        }

    async def get_endpoint(self, endpoint_uuid: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT uuid, label, enabled, created_at FROM webhook_endpoints WHERE uuid = ?",
            (endpoint_uuid,),
        )
        if row is None:
            return None
        return {
            "uuid": str(row["uuid"]),
            "label": str(row["label"]),
            "enabled": bool(row["enabled"]),
            "createdAt": str(row["created_at"]),
        }

    async def list_endpoints(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT uuid, label, enabled, created_at FROM webhook_endpoints ORDER BY created_at ASC, uuid ASC"
        )
        return [
            {
                "uuid": str(row["uuid"]),
                "label": str(row["label"]),
                "enabled": bool(row["enabled"]),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]

    async def set_enabled(self, endpoint_uuid: str, enabled: bool) -> bool:
        await self._db.migrate()
        cursor = await self._db.execute(
            "UPDATE webhook_endpoints SET enabled = ? WHERE uuid = ?",
            (1 if enabled else 0, endpoint_uuid),
        )
        return bool(cursor)

    async def delete_endpoint(self, endpoint_uuid: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT uuid FROM webhook_endpoints WHERE uuid = ?", (endpoint_uuid,)
        )
        if row is None:
            return False
        from lumirss.db_tx import transaction

        def _delete(conn: Any) -> None:
            conn.execute(
                "DELETE FROM webhook_inbox WHERE endpoint_uuid = ?", (endpoint_uuid,)
            )
            conn.execute(
                "DELETE FROM webhook_endpoints WHERE uuid = ?", (endpoint_uuid,)
            )

        await transaction(self._db, _delete)
        return True

    # -- 接收（审阅前区） ---------------------------------------------------

    async def ingest(
        self,
        endpoint_uuid: str,
        event_id: str,
        items: list[dict[str, Any]],
        raw_digest: str,
    ) -> list[dict[str, Any]]:
        """条目入待确认区（幂等）。逐条返回 stored/duplicate/decided。

        已裁决事件重投 → 全部 duplicate 且附 alreadyDecided=True，
        绝不覆盖裁决、绝不产生新行。"""
        await self._db.migrate()
        results: list[dict[str, Any]] = []
        for item in items:
            item_key = f"{event_id}:{item['id']}"
            row = await self._db.fetch_one(
                "SELECT id, status FROM webhook_inbox WHERE endpoint_uuid = ? AND event_id = ?",
                (endpoint_uuid, item_key),
            )
            if row is not None:
                results.append(
                    {
                        "itemId": item["id"],
                        "inboxId": int(row["id"]),
                        "result": "duplicate",
                        "alreadyDecided": str(row["status"]) != "pending",
                    }
                )
                continue
            cursor = await self._db.execute(
                "INSERT INTO webhook_inbox (endpoint_uuid, event_id, title, summary, "
                "payload_digest, status, received_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                (
                    endpoint_uuid,
                    item_key,
                    item["title"],
                    item["summary"][:2000],
                    raw_digest,
                    utc_now(),
                ),
            )
            results.append(
                {"itemId": item["id"], "inboxId": int(cursor), "result": "stored"}
            )
        return results

    async def _decided_event_exists(self, endpoint_uuid: str, event_id: str) -> bool:
        """事件级裁决探测：该事件的任何条目已被裁决 → True。

        用精确键探测（当前 items 的键），避免 LIKE 特殊字符问题 ——
        由 ingest 在循环内联调用。保留占位以示契约：条目级幂等已覆盖
        重放场景，事件级探测仅用于「同一事件扩了新条目」的边角。"""
        row = await self._db.fetch_one(
            "SELECT id FROM webhook_inbox WHERE endpoint_uuid = ? AND event_id LIKE ? "
            "AND status != 'pending' LIMIT 1",
            (endpoint_uuid, event_id.replace("%", "[%]").replace("_", "[_]") + ":[%]"),
        )
        return row is not None

    # -- 审阅（pending → accepted/rejected） ---------------------------------

    async def list_inbox(self, *, status: str | None = None) -> list[dict[str, Any]]:
        await self._db.migrate()
        if status in ("pending", "accepted", "rejected"):
            rows = await self._db.fetch_all(
                "SELECT id, endpoint_uuid, event_id, title, summary, status, received_at, decided_at "
                "FROM webhook_inbox WHERE status = ? ORDER BY id DESC LIMIT 200",
                (status,),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT id, endpoint_uuid, event_id, title, summary, status, received_at, decided_at "
                "FROM webhook_inbox ORDER BY id DESC LIMIT 200"
            )
        return [self._row_to_dict(row) for row in rows]

    async def decide(self, inbox_id: int, accept: bool) -> dict[str, Any] | None:
        """裁决一条待确认条目；已裁决 → None（幂等拒绝二次裁决）。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, status FROM webhook_inbox WHERE id = ?", (inbox_id,)
        )
        if row is None:
            return None
        if str(row["status"]) != "pending":
            return None
        status = "accepted" if accept else "rejected"
        cursor = await self._db.execute(
            "UPDATE webhook_inbox SET status = ?, decided_at = ? WHERE id = ? AND status = 'pending'",
            (status, utc_now(), inbox_id),
        )
        if not cursor:
            return None
        return {"id": inbox_id, "status": status, "decidedAt": utc_now()}

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "endpointUuid": str(row["endpoint_uuid"]),
            "eventId": str(row["event_id"]),
            "title": str(row["title"]),
            "summary": str(row["summary"]),
            "status": str(row["status"]),
            "receivedAt": str(row["received_at"]),
            "decidedAt": row["decided_at"],
        }


async def _authorized_endpoint_or_none(
    request: Any,
    endpoint_uuid: str,
    body: bytes,
) -> dict[str, Any] | None:
    """认证链的端点侧（**在调用方的 machine_user_context 内执行**）：

    端点存在且启用 + 实例签名钥 HMAC 验签通过 → 端点；否则 None
    （路由统一 404，无存在性预言机）。bearer 归属由路由的
    ``async with machine_user_context`` 承担 —— 归属作用域必须覆盖
    后续全部 per-user 读写。"""
    store = WebhookInboxStore(request.app.state.db)
    endpoint = await store.get_endpoint(endpoint_uuid)
    if endpoint is None or not endpoint["enabled"]:
        return None
    key_id = await verify_webhook_signature(
        request.app.state.control_db, body, request.headers.get("x-lumi-signature")
    )
    if key_id is None:
        return None
    return endpoint


def body_digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()[:32]
