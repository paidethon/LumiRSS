"""NEW-346 设备信任期限 —— 当前设备的敏感操作信任到期日。

- 授予 = 密码复核通过后，为当前设备指纹（UA 族|平台 的 SHA-256
  前 16 位，与 N008 同一口径）写 trusted_until = now + hours；
- 到期必须重新验证（判定是纯函数 ``is_trusted``）；吊销随时可做；
- 硬边界：授予/续期**绝不创建或延长 auth_sessions** —— 服务端会话
  的过期时间原样不动（测试断言授予前后 session 状态不变）；
- 消费方（真实执行点）：NEW-344 的 full（完整授权正文）共享链接
  创建 —— 对外发布完整正文是敏感操作；其余发布/撤销仍走普通鉴权。

per-user：表在 per-user 库；A 的设备信任对 B 不存在。
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MIN_HOURS = 1
MAX_HOURS = 720

TRUST_PURPOSE_FULL_SHARE = "share_link_full_scope"


class DeviceTrustInvalid(ValueError):
    """信任负载非法（映射 422）。"""


class DeviceTrustDenied(Exception):
    """密码复核失败（映射 401 invalid_credentials）。"""


def clean_hours(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise DeviceTrustInvalid("hours 必须是整数。")
    if not MIN_HOURS <= raw <= MAX_HOURS:
        raise DeviceTrustInvalid(f"hours 必须在 {MIN_HOURS}..{MAX_HOURS} 之间。")
    return raw


def is_trusted(row: dict[str, Any] | None, *, now: datetime | None = None) -> bool:
    """纯函数判定：存在且未到期 → True（到期/无授予 → False）。"""
    if row is None:
        return False
    moment = now or datetime.now(UTC)
    try:
        until = datetime.fromisoformat(str(row["trustedUntil"]))
    except ValueError:
        return False
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    return until > moment


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


async def grant_trust(
    db: Database,
    *,
    fingerprint: str,
    device_label: str,
    verify_password: Any,
    hours: int,
) -> dict[str, Any]:
    """密码复核（回调由路由用控制库实现）→ 授予/续期当前设备信任。

    绝不触碰 auth_sessions —— 会话的过期时间原样不动。"""
    clean = clean_hours(hours)
    if not await verify_password():
        raise DeviceTrustDenied("password mismatch")
    now = datetime.now(UTC)
    until = _iso(now + timedelta(hours=clean))
    existing = await db.fetch_one(
        "SELECT trusted_until FROM device_trust_grants WHERE device_fingerprint = ?",
        (fingerprint,),
    )
    renewed = existing is not None
    await db.execute(
        "INSERT INTO device_trust_grants (device_fingerprint, device_label,"
        " trusted_until, created_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(device_fingerprint) DO UPDATE SET trusted_until ="
        " excluded.trusted_until, renewed_at = excluded.created_at",
        (fingerprint, device_label, until, utc_now()),
    )
    return {
        "deviceFingerprint": fingerprint[:8],
        "deviceLabel": device_label,
        "trustedUntil": until,
        "hours": clean,
        "renewed": renewed,
        "note": "设备信任不创建也不延长服务端会话；会话到期行为不变。",
    }


async def current_grant(db: Database, fingerprint: str) -> dict[str, Any] | None:
    await db.migrate()
    row = await db.fetch_one(
        "SELECT device_fingerprint, device_label, trusted_until, created_at,"
        " renewed_at FROM device_trust_grants WHERE device_fingerprint = ?",
        (fingerprint,),
    )
    if row is None:
        return None
    return {
        "deviceFingerprint": str(row["device_fingerprint"])[:8],
        "deviceLabel": str(row["device_label"]),
        "trustedUntil": str(row["trusted_until"]),
        "createdAt": str(row["created_at"]),
        "renewedAt": row["renewed_at"],
    }


async def list_grants(db: Database) -> list[dict[str, Any]]:
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT device_fingerprint, device_label, trusted_until, created_at"
        " FROM device_trust_grants ORDER BY trusted_until DESC"
    )
    now = datetime.now(UTC)
    return [
        {
            "deviceFingerprint": str(row["device_fingerprint"])[:8],
            "deviceLabel": str(row["device_label"]),
            "trustedUntil": str(row["trusted_until"]),
            "createdAt": str(row["created_at"]),
            "trusted": is_trusted({"trustedUntil": str(row["trusted_until"])}, now=now),
        }
        for row in rows
    ]


async def revoke_trust(db: Database, fingerprint: str) -> bool:
    await db.migrate()

    import sqlite3

    from lumirss.db_tx import transaction

    def _tx(conn: sqlite3.Connection) -> bool:
        cursor = conn.execute(
            "DELETE FROM device_trust_grants WHERE device_fingerprint = ?",
            (fingerprint,),
        )
        return bool(cursor.rowcount)

    return bool(await transaction(db, _tx))


async def revoke_trust_by_prefix(db: Database, prefix: str) -> bool:
    """按指纹（或其 8 位前缀）吊销 —— 列表展示只给前缀，撤销用前缀。"""
    await db.migrate()

    import sqlite3

    from lumirss.db_tx import transaction

    def _tx(conn: sqlite3.Connection) -> bool:
        cursor = conn.execute(
            "DELETE FROM device_trust_grants WHERE device_fingerprint = ?"
            " OR substr(device_fingerprint, 1, ?) = ?",
            (prefix, len(prefix), prefix),
        )
        return bool(cursor.rowcount)

    return bool(await transaction(db, _tx))


def fingerprint_of_request(request: Any) -> tuple[str, str]:
    """请求 → (设备指纹, 脱敏标签)。与 N008 同一 UA 解析口径。"""
    from lumirss.auth_store import device_fingerprint, device_label_from_ua

    ua = request.headers.get("user-agent")
    return device_fingerprint(ua), device_label_from_ua(ua)
