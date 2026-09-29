"""NEW-308 外发 Webhook 事件订阅 —— 用户选择本人数据的少量事件。

- 事件词表刻意收窄（entry.starred / library.item_created /
  reading.progress_changed）—— 发送范围如实展示（类型 + 目标主机）；
- 目标地址必须 https（与 api_sources.validate_endpoint 同一基线，
  操作员允许清单内的私有主机可 http —— e2e 固定装置）；投递前再走
  validate_hop（SSRF 守卫，继承 clips/api_sources 的同一基线）；
- 授权两步：创建 → pending（verify token 明文只出现一次）→ 用户在
  目标端确认后 verify → active；pause/resume/revoke 全部显式入口；
- 签名：每次投递带 X-Lumi-Signature（HMAC-SHA256，订阅秘密经
  SecretsStore（0600 库外文件）保存 —— 可逆但不出库备份，签名时读回；
  秘密绝不回显任何响应）；
- sender 可注入（测试假传输）；真实发送走 SSRF 校验的客户端；
- per-user：订阅与秘密都在 per-user 范围（RoutingDatabase +
  per-user secrets 文件），A 的订阅对 B 不可见（显式隔离测试）。
"""

import hashlib
import hmac
import secrets as _secrets
import time
import uuid as _uuid
from typing import Any

from lumirss.api_sources import validate_endpoint
from lumirss.new309_delivery_receipts import sanitize_response_excerpt
from lumirss.storage import Database
from lumirss.token_hash import hash_token, verify_token
from lumirss.util import utc_now

EVENT_TYPES: tuple[str, ...] = (
    "entry.starred",
    "library.item_created",
    "reading.progress_changed",
)
_MAX_SUBSCRIPTIONS = 20
_MAX_PAYLOAD_BYTES = 8 * 1024
_SECRET_KEY_PREFIX = "webhook_out_secret:"


class OutboundSubscriptionInvalid(ValueError):
    """订阅负载非法（映射 422）。"""


class OutboundSubscriptionNotFound(Exception):
    """No such subscription (for this user)."""


def clean_event_type(raw: Any) -> str:
    if raw not in EVENT_TYPES:
        raise OutboundSubscriptionInvalid(
            f"eventType 必须是 {'、'.join(EVENT_TYPES)} 之一。"
        )
    return str(raw)


class OutboundSubscriptionStore:
    def __init__(self, db: Database, secrets: Any) -> None:
        self._db = db
        self._secrets = secrets

    # -- CRUD ----------------------------------------------------------------

    async def create(self, event_type: Any, target_url: Any) -> dict[str, Any]:
        event = clean_event_type(event_type)
        if not isinstance(target_url, str) or not target_url.strip():
            raise OutboundSubscriptionInvalid("targetUrl 不能为空。")
        try:
            clean_url = validate_endpoint(target_url)
        except Exception as exc:
            raise OutboundSubscriptionInvalid(f"targetUrl 不合格：{exc}") from exc
        await self._db.migrate()
        count = await self._db.fetch_one("SELECT COUNT(*) AS n FROM webhook_out_subscriptions")
        if count is not None and int(count["n"]) >= _MAX_SUBSCRIPTIONS:
            raise OutboundSubscriptionInvalid(f"最多 {_MAX_SUBSCRIPTIONS} 条订阅，请先撤销旧的。")
        row = await self._db.fetch_one(
            "SELECT id FROM webhook_out_subscriptions WHERE event_type = ? AND target_url = ?",
            (event, clean_url),
        )
        if row is not None:
            raise OutboundSubscriptionInvalid("同一事件类型与目标地址的订阅已存在。")
        secret = _secrets.token_hex(24)
        verify_token_plain = _secrets.token_urlsafe(24)
        cursor = await self._db.execute(
            "INSERT INTO webhook_out_subscriptions (event_type, target_url, secret_hash, "
            "state, verify_token_hash, created_at) VALUES (?, ?, ?, 'pending', ?, ?)",
            (event, clean_url, hash_token(secret), hash_token(verify_token_plain), utc_now()),
        )
        subscription_id = int(cursor)
        self._secrets.set(f"{_SECRET_KEY_PREFIX}{subscription_id}", secret)
        return {
            "id": subscription_id,
            "eventType": event,
            "targetUrl": clean_url,
            "state": "pending",
            "secret": secret,
            "verifyToken": verify_token_plain,
            "createdAt": utc_now(),
        }

    async def get(self, subscription_id: int) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, event_type, target_url, state, created_at, verified_at "
            "FROM webhook_out_subscriptions WHERE id = ?",
            (subscription_id,),
        )
        return dict(row) if row is not None else None

    async def list_subscriptions(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, event_type, target_url, state, created_at, verified_at "
            "FROM webhook_out_subscriptions ORDER BY id ASC"
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            entry = dict(row)
            entry["targetHost"] = _host_of(str(row["target_url"]))
            result.append(entry)
        return result

    async def verify(self, subscription_id: int, token: Any) -> bool:
        """verify token 单次有效；通过 → active（并清除 token 散列）。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, verify_token_hash FROM webhook_out_subscriptions WHERE id = ? AND state = 'pending'",
            (subscription_id,),
        )
        if row is None or not isinstance(token, str):
            return False
        if not verify_token(token, row["verify_token_hash"]):
            return False
        await self._db.execute(
            "UPDATE webhook_out_subscriptions SET state = 'active', verified_at = ?, "
            "verify_token_hash = NULL WHERE id = ?",
            (utc_now(), subscription_id),
        )
        return True

    async def set_state(self, subscription_id: int, state: str) -> bool:
        if state not in ("active", "paused", "revoked"):
            raise OutboundSubscriptionInvalid("非法状态。")
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT state, verified_at FROM webhook_out_subscriptions WHERE id = ?",
            (subscription_id,),
        )
        if row is None:
            return False
        current = str(row["state"])
        if current == "revoked":
            # 终态不可逆 —— 与「不存在」(404) 区分，映射 409。
            raise OutboundSubscriptionInvalid("订阅已撤销（终态，不可再变更）。")
        if state == "active" and row["verified_at"] is None:
            # 激活（含 paused→resume）必须以「目标地址已验证」为前提；
            # pending 或未验证的暂停态一律 409，验证门不可绕过。
            raise OutboundSubscriptionInvalid("订阅尚未通过目标地址验证，不能激活。")
        await self._db.execute(
            "UPDATE webhook_out_subscriptions SET state = ? WHERE id = ?",
            (state, subscription_id),
        )
        return True

    # -- 投递 ------------------------------------------------------------------

    async def active_subscriptions_for(self, event_type: str) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, event_type, target_url FROM webhook_out_subscriptions "
            "WHERE event_type = ? AND state = 'active'",
            (event_type,),
        )
        return [dict(row) for row in rows]

    def secret_for(self, subscription_id: int) -> str | None:
        return self._secrets.get(f"{_SECRET_KEY_PREFIX}{subscription_id}")

    def delete_secret(self, subscription_id: int) -> None:
        self._secrets.delete(f"{_SECRET_KEY_PREFIX}{subscription_id}")

    def build_payload(
        self,
        *,
        subscription_id: int,
        event_type: str,
        data: dict[str, Any],
        event_uuid: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[bytes, str, str]:
        """(body, event_uuid, idempotency_key)：有界、含幂等键。

        重试（NEW-309）传入原 (event_uuid, idempotency_key) —— 信封与
        幂等头保持一致，接收端凭该键去重。"""
        event_uuid = event_uuid or str(_uuid.uuid4())
        idempotency_key = idempotency_key or hashlib.sha256(
            f"{subscription_id}:{event_uuid}".encode()
        ).hexdigest()[:32]
        import json

        body = json.dumps(
            {
                "eventType": event_type,
                "eventId": event_uuid,
                "idempotencyKey": idempotency_key,
                "occurredAt": utc_now(),
                "data": data,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > _MAX_PAYLOAD_BYTES:
            raise OutboundSubscriptionInvalid("事件载荷超过 8KB 上限。")
        return body, event_uuid, idempotency_key


def sign_payload(secret: str, body: bytes) -> str:
    timestamp = int(time.time())
    material = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    digest = hmac.new(
        material.encode("utf-8"), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


async def dispatch_event(
    store: OutboundSubscriptionStore,
    deliveries: Any,
    event_type: str,
    data: dict[str, Any],
    *,
    sender: Any = None,
) -> list[dict[str, Any]]:
    """向该事件类型的全部 active 订阅投递；逐订阅记录回执（NEW-309）。

    ``sender(url, headers, body) -> (status, content_type, body_text)``
    可注入；生产实现（SSRF 校验）在路由层组装。投递失败不中断其它
    订阅 —— 每个订阅独立尝试、独立回执。"""
    clean = clean_event_type(event_type)
    subs = await store.active_subscriptions_for(clean)
    results: list[dict[str, Any]] = []
    send = sender or _http_sender
    for sub in subs:
        subscription_id = int(sub["id"])
        try:
            body, event_uuid, idempotency_key = store.build_payload(
                subscription_id=subscription_id, event_type=clean, data=data
            )
        except OutboundSubscriptionInvalid as exc:
            results.append(
                {"subscriptionId": subscription_id, "ok": False, "error": str(exc)}
            )
            continue
        secret = store.secret_for(subscription_id)
        if not secret:
            results.append(
                {
                    "subscriptionId": subscription_id,
                    "ok": False,
                    "error": "签名秘密缺失（订阅不可投递，请撤销重建）。",
                }
            )
            continue
        headers = {
            "Content-Type": "application/json",
            "X-Lumi-Event": clean,
            "X-Lumi-Delivery": idempotency_key,
            "X-Lumi-Signature": sign_payload(secret, body),
        }
        try:
            status, content_type, body_text = await send(sub["target_url"], headers, body)
        except Exception as exc:
            await deliveries.record_attempt(
                subscription_id=subscription_id,
                event_type=clean,
                event_uuid=event_uuid,
                idempotency_key=idempotency_key,
                attempt=1,
                ok=False,
                response_status=None,
                response_excerpt=f"[network] {type(exc).__name__}",
            )
            results.append(
                {"subscriptionId": subscription_id, "ok": False, "error": "network_error"}
            )
            continue
        ok = 200 <= status < 300
        await deliveries.record_attempt(
            subscription_id=subscription_id,
            event_type=clean,
            event_uuid=event_uuid,
            idempotency_key=idempotency_key,
            attempt=1,
            ok=ok,
            response_status=status,
            response_excerpt=sanitize_response_excerpt(content_type, body_text),
        )
        results.append(
            {"subscriptionId": subscription_id, "ok": ok, "responseStatus": status}
        )
    return results


async def _http_sender(url: str, headers: dict[str, str], body: bytes) -> tuple[int, str, str]:
    """生产发送：SSRF 校验（validate_hop）→ 有界响应读取。"""
    import httpx

    from lumirss.api_sources import _FETCH_TIMEOUT_SECONDS
    from lumirss.clip_fetch import validate_hop

    await validate_hop(url)
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.post(
            url,
            content=body,
            headers=headers,
            timeout=_FETCH_TIMEOUT_SECONDS,
            follow_redirects=False,
        )
        text = response.text[:2048]
        return response.status_code, response.headers.get("content-type", ""), text


def _host_of(url: str) -> str:
    import urllib.parse

    parts = urllib.parse.urlsplit(url)
    return parts.netloc
