"""NEW-248 来源链接去追踪预览 —— 预览移除清单 + 用户保留参数。

语义边界（模块存在的理由）：

- 预览是**纯计算**（零写入）：内置已知追踪参数清单（与 F004/F010
  同一口径：utm_*、fbclid、gclid、msclkid、igshid、mc_cid、mc_eid）；
- 绝不删除：签名/授权参数（token、sig、key、access_token、*_signature）
  与一切清单外未知参数——未知 = 保守保留，绝不猜；登录态 / 内容选择
  参数因此天然存活；
- 用户保留表（detrack_kept_params）：用户显式标记「必须保留」的参数
  （理由可选）；预览遇到它 → 归入 kept（even if 名单命中）；
  可撤销（DELETE）恢复可移除态；
- 预览输出三组：removed（将移除）/ keptRequired（保护类 + 未知）/
  keptUser（用户标记）+ cleanedUrl；非 http(s) 或解析失败 → 诚实
  unsupported（不做任何移除）。

per-user 库：保留表天然按账户隔离。
"""

import sqlite3
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now

TRACKING_EXACT = frozenset({"fbclid", "gclid", "msclkid", "igshid", "mc_cid", "mc_eid"})
TRACKING_PREFIXES = ("utm_",)
PROTECTED_EXACT = frozenset({"token", "sig", "key", "access_token"})
_REASON_MAX = 300
_PARAM_MAX = 100


class DetrackInvalid(ValueError):
    """预览/保留参数负载非法（映射 422）。"""


def is_tracking_param(name: str) -> bool:
    lowered = name.lower()
    if lowered in PROTECTED_EXACT or lowered.endswith("_signature"):
        return False
    if lowered in TRACKING_EXACT:
        return True
    return any(lowered.startswith(prefix) for prefix in TRACKING_PREFIXES)


def preview_detrack(url: str, kept_user: set[str]) -> dict[str, Any]:
    """纯函数：给定 URL 与用户保留集 → 移除/保留分组 + 清理后 URL。"""
    if not isinstance(url, str) or not url.strip():
        raise DetrackInvalid("url 不能为空。")
    if len(url) > 4000:
        raise DetrackInvalid("url 超出 4000 字符上限。")
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return {"supported": False, "reason": "unparsable"}
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return {"supported": False, "reason": "unsupported_scheme"}

    pairs = parse_qsl(parts.query, keep_blank_values=True)
    removed: list[str] = []
    kept_required: list[str] = []
    kept_by_user: list[str] = []
    surviving: list[tuple[str, str]] = []
    for name, value in pairs:
        lowered = name.lower()
        if lowered in kept_user:
            kept_by_user.append(name)
            surviving.append((name, value))
        elif is_tracking_param(name):
            removed.append(name)
        else:
            # 保护类（签名/授权）与一切清单外未知参数：保守保留
            kept_required.append(name)
            surviving.append((name, value))

    cleaned_query = urlencode(surviving)
    cleaned_parts = (parts.scheme, parts.netloc, parts.path, cleaned_query, parts.fragment)
    from urllib.parse import urlunsplit

    return {
        "supported": True,
        "removed": removed,
        "keptRequired": kept_required,
        "keptUser": kept_by_user,
        "cleanedUrl": urlunsplit(cleaned_parts),
    }


class DetrackStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def preview(self, url: str) -> dict[str, Any]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT param FROM detrack_kept_params",
            (),
        )
        kept_user = {str(row["param"]) for row in rows}
        result = preview_detrack(url, kept_user)
        result["url"] = url
        return result

    # -- 用户保留参数 ---------------------------------------------------------

    @staticmethod
    def _validate_param(param: str) -> str:
        if not isinstance(param, str) or not 1 <= len(param.strip()) <= _PARAM_MAX:
            raise DetrackInvalid("参数名必须是 1-100 个字符。")
        if "=" in param or "&" in param or param.strip() != param:
            raise DetrackInvalid("参数名不能含 = & 或首尾空白。")
        return param.strip()

    async def put_kept_param(self, param: str, reason: str) -> dict[str, Any]:
        clean_param = self._validate_param(param)
        if not isinstance(reason, str) or len(reason.strip()) > _REASON_MAX:
            raise DetrackInvalid(f"reason 最多 {_REASON_MAX} 个字符。")
        clean_reason = reason.strip()
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            row = conn.execute(
                "SELECT param FROM detrack_kept_params WHERE param = ?", (clean_param,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO detrack_kept_params (param, reason, created_at) VALUES (?, ?, ?)",
                    (clean_param, clean_reason, now),
                )
            else:
                conn.execute(
                    "UPDATE detrack_kept_params SET reason = ? WHERE param = ?",
                    (clean_reason, clean_param),
                )

        await transaction(self._db, _tx)
        return {"param": clean_param, "reason": clean_reason}

    async def delete_kept_param(self, param: str) -> None:
        clean_param = self._validate_param(param)

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM detrack_kept_params WHERE param = ?", (clean_param,))

        await transaction(self._db, _tx)

    async def list_kept_params(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT param, reason, created_at FROM detrack_kept_params ORDER BY created_at DESC, param",
            (),
        )
        return [
            {
                "param": str(row["param"]),
                "reason": str(row["reason"]),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]
