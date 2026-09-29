"""NEW-304 Webhook 密钥轮换窗口 —— 管理员在受控秘密通道轮换签名密钥。

- 轮换 = 铸造新钥（明文只在轮换响应出现一次，库里只有散列）并把
  上一把 active 钥降级为 retiring，带短暂双钥窗口（1..60 分钟，
  默认 10）—— 窗口内新旧两把钥都能通过验证，发送方不必同步切换；
- 验证用 ``hmac.compare_digest``（timing-safe），时间戳偏移超过
  max_skew 直接拒绝（防重放）；
- 切换结果 = 每钥每日成功验证计数（新钥计数上升、旧钥计数趋零）；
  报告只含 key_id / 状态 / 计数，绝不回显任何密钥材料；
- 非管理员不可达（路由层 admin guard + step-up，op =
  ``webhook_key_rotation``，target = 管理员本人 id —— 轮换是实例级
  操作，作用域仍逐字绑定以防令牌转投其他敏感操作）。

per-user：签名钥是实例级（control 库）；per-user 隔离体现在路由层
—— 非 admin 成员（A/B）一律 403，且列表响应不含任何秘密。
"""

import hashlib
import hmac
import secrets as _secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from lumirss.token_hash import hash_token

KEY_STATE_ACTIVE = "active"
KEY_STATE_RETIRED = "retiring"
_DEFAULT_WINDOW_MINUTES = 10
_MIN_WINDOW_MINUTES = 1
_MAX_WINDOW_MINUTES = 60
_MAX_SKEW_SECONDS = 300
_VERIFY_TTL_DAYS = 7
_MAX_KEYS = 8


class KeyRotationInvalid(ValueError):
    """轮换参数非法（映射 422）。"""


def clean_window_minutes(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise KeyRotationInvalid("windowMinutes 必须是整数。")
    if not _MIN_WINDOW_MINUTES <= raw <= _MAX_WINDOW_MINUTES:
        raise KeyRotationInvalid(
            f"windowMinutes 必须在 {_MIN_WINDOW_MINUTES}..{_MAX_WINDOW_MINUTES} 之间。"
        )
    return raw


def _day_key(moment: datetime) -> str:
    return moment.astimezone().strftime("%Y-%m-%d")


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def signing_material(secret: str) -> str:
    """发送方从明文钥派生的 HMAC 材料 = 存储散列本身（sha256(secret)）。

    服务端不存明文，只存该派生值；持有明文钥的发送方可自行算出同一
    值 —— 泄漏数据库拿不到明文钥，泄漏明文钥才影响签名，与凭证的
    威胁模型一致。"""
    return hash_token(secret)


def signature_header(timestamp: int, body: bytes, secret: str) -> str:
    """发送方的签名头形状（测试与文档共用）：HMAC-SHA256(派生材料,
    "{t}.{body}")，t 为 unix 秒。"""
    material = signing_material(secret)
    digest = hmac.new(
        material.encode("utf-8"), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


class SigningKeyStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def rotate(self, window_minutes: int = _DEFAULT_WINDOW_MINUTES) -> dict[str, Any]:
        """铸造新钥并开启双钥窗口。返回明文 secret（仅此一次）。"""
        clean_window = clean_window_minutes(window_minutes)
        await self._db.migrate()
        now = datetime.now(UTC)
        secret = _secrets.token_hex(32)
        key_id = "wk_" + _secrets.token_hex(6)
        await self._db.execute(
            "INSERT INTO webhook_signing_keys (key_id, key_hash, state, created_at, window_ends_at) "
            "VALUES (?, ?, ?, ?, NULL)",
            (key_id, hash_token(secret), KEY_STATE_ACTIVE, _iso(now)),
        )
        previous = await self._db.fetch_one(
            "SELECT key_id FROM webhook_signing_keys "
            "WHERE state = ? AND key_id != ? ORDER BY created_at DESC LIMIT 1",
            (KEY_STATE_ACTIVE, key_id),
        )
        previous_key_id: str | None = None
        if previous is not None:
            previous_key_id = str(previous["key_id"])
            window_ends = _iso(now + timedelta(minutes=clean_window))
            await self._db.execute(
                "UPDATE webhook_signing_keys SET state = ?, window_ends_at = ? WHERE key_id = ?",
                (KEY_STATE_RETIRED, window_ends, previous_key_id),
            )
        # 顺带清窗：过窗口的 retiring 钥降级 + 过期验证计数清理，表有界。
        await self._db.execute(
            "UPDATE webhook_signing_keys SET state = 'expired', window_ends_at = NULL "
            "WHERE state = ? AND window_ends_at IS NOT NULL AND window_ends_at <= ?",
            (KEY_STATE_RETIRED, _iso(now)),
        )
        cutoff = _iso(now - timedelta(days=_VERIFY_TTL_DAYS))
        await self._db.execute(
            "DELETE FROM webhook_key_verifications WHERE day_key < ?",
            (cutoff[:10],),
        )
        count = await self._db.fetch_one("SELECT COUNT(*) AS n FROM webhook_signing_keys")
        if count is not None and int(count["n"]) > _MAX_KEYS:
            await self._db.execute(
                "DELETE FROM webhook_signing_keys WHERE key_id IN ("
                "SELECT key_id FROM webhook_signing_keys WHERE state = 'expired' "
                "ORDER BY created_at ASC LIMIT ?)",
                (int(count["n"]) - _MAX_KEYS,),
            )
        return {
            "keyId": key_id,
            "secret": secret,
            "windowMinutes": clean_window,
            "previousKeyId": previous_key_id,
        }

    async def candidate_keys(self, *, now: datetime | None = None) -> list[tuple[str, str]]:
        """(key_id, key_hash) 候选：active 优先，未过窗的 retiring 次之。"""
        await self._db.migrate()
        moment = now or datetime.now(UTC)
        rows = await self._db.fetch_all(
            "SELECT key_id, key_hash, state, window_ends_at FROM webhook_signing_keys "
            "ORDER BY CASE state WHEN ? THEN 0 WHEN ? THEN 1 ELSE 2 END, created_at DESC",
            (KEY_STATE_ACTIVE, KEY_STATE_RETIRED),
        )
        candidates: list[tuple[str, str]] = []
        for row in rows:
            state = str(row["state"])
            if state == KEY_STATE_ACTIVE:
                candidates.append((str(row["key_id"]), str(row["key_hash"])))
            elif state == KEY_STATE_RETIRED:
                ends = row["window_ends_at"]
                if ends is None:
                    continue
                try:
                    ends_at = datetime.fromisoformat(str(ends).replace("Z", "+00:00"))
                except ValueError:
                    continue
                if ends_at >= moment:
                    candidates.append((str(row["key_id"]), str(row["key_hash"])))
        return candidates

    async def record_verification(self, key_id: str, *, now: datetime | None = None) -> None:
        moment = now or datetime.now(UTC)
        await self._db.execute(
            "INSERT INTO webhook_key_verifications (key_id, day_key, success_count) VALUES (?, ?, 1) "
            "ON CONFLICT(key_id, day_key) DO UPDATE SET success_count = success_count + 1",
            (key_id, _day_key(moment)),
        )

    async def snapshot(self) -> dict[str, Any]:
        """切换结果视图：每钥状态/窗口/验证计数。绝无密钥材料。"""
        await self._db.migrate()
        now = datetime.now(UTC)
        keys = await self._db.fetch_all(
            "SELECT key_id, state, created_at, window_ends_at FROM webhook_signing_keys "
            "ORDER BY created_at DESC"
        )
        counters = await self._db.fetch_all(
            "SELECT key_id, day_key, success_count FROM webhook_key_verifications ORDER BY day_key ASC"
        )
        per_key: dict[str, dict[str, int]] = {}
        for row in counters:
            slot = per_key.setdefault(str(row["key_id"]), {"today": 0, "total": 0})
            slot["total"] += int(row["success_count"])
            if str(row["day_key"]) == _day_key(now):
                slot["today"] += int(row["success_count"])
        payload: list[dict[str, Any]] = []
        for row in keys:
            key_id = str(row["key_id"])
            counts = per_key.get(key_id, {"today": 0, "total": 0})
            payload.append(
                {
                    "keyId": key_id,
                    "state": str(row["state"]),
                    "createdAt": str(row["created_at"]),
                    "windowEndsAt": row["window_ends_at"],
                    "verifiedToday": counts["today"],
                    "verifiedTotal": counts["total"],
                }
            )
        return {
            "keys": payload,
            "honestyNote": "报告不含任何密钥材料；新钥计数上升且旧钥归零即切换完成。",
        }


async def verify_webhook_signature(
    db: Any,
    body: bytes,
    header_value: str | None,
    store: SigningKeyStore | None = None,
    *,
    now: datetime | None = None,
) -> str | None:
    """验签 → 命中的 key_id；任何一步不匹配 → None（路由回 404）。

    timing-safe：对每个候选钥都走 ``hmac.compare_digest``；时间戳超出
    ±max_skew 或头形状非法直接拒绝。命中后累加该钥的验证计数（切换
    结果可见）。"""
    if not header_value:
        return None
    timestamp_text: str | None = None
    supplied_digest: str | None = None
    for part in header_value.split(","):
        part = part.strip()
        if part.startswith("t="):
            timestamp_text = part[2:]
        elif part.startswith("v1="):
            supplied_digest = part[3:]
    if not timestamp_text or not supplied_digest or not timestamp_text.isdigit():
        return None
    moment = now or datetime.now(UTC)
    timestamp = int(timestamp_text)
    skew = abs((datetime.fromtimestamp(timestamp, tz=UTC) - moment).total_seconds())
    if skew > _MAX_SKEW_SECONDS:
        return None
    store = store or SigningKeyStore(db)
    expected_prefix = f"{timestamp}.".encode() + body
    for key_id, key_hash in await store.candidate_keys(now=moment):
        # HMAC 材料 = 存储散列（sha256(明文钥)）；发送方持有明文钥时
        # 可派生出同一材料。常量时间比对，逐候选尝试。
        expected = hmac.new(
            key_hash.encode("utf-8"), expected_prefix, hashlib.sha256
        ).hexdigest()
        if hmac.compare_digest(expected, supplied_digest):
            await store.record_verification(key_id, now=moment)
            return key_id
    return None
