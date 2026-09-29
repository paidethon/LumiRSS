"""NEW-294 通讯订阅来源映射 —— 用户把某发件地址映射为个人资料来源，
之后同来源邮件自动归入该视图。

诚实口径（硬规则）：

- 映射是精确地址匹配（小写化后全等），绝不做域名通配或模糊猜测；
  用户没映射的地址不归任何来源（source_label 为空 = 未归源）；
- 「自动归入」只发生在导入流水线里（新邮件按当时的映射表落标签）；
  修改映射不追溯重写已入库条目（如实说明，需要时用户可重新导入或
  手动改用导出/编辑路径）——避免静默改历史；
- 视图 = 按 source_label 过滤的资料清单（GET /email-materials?source=）。

per-user：映射表在 per-user 库，A 的映射对 B 不存在、不影响 B 的导入。
"""

from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

HONESTY_NOTE = (
    "映射按发件地址精确匹配（大小写不敏感）；只对映射之后导入的邮件"
    "自动归源，不追溯改写已入库条目。"
)

_MAX_LABEL = 120


class SourceMapInvalid(ValueError):
    """映射负载非法（映射 422）。"""


def clean_pair(from_addr: Any, source_label: Any) -> tuple[str, str]:
    if not isinstance(from_addr, str) or "@" not in from_addr:
        raise SourceMapInvalid("fromAddr 必须是邮箱地址（包含 @）。")
    addr = from_addr.strip().lower()
    if len(addr) > 320:
        raise SourceMapInvalid("fromAddr 过长（≤320）。")
    if not isinstance(source_label, str) or not source_label.strip():
        raise SourceMapInvalid("sourceLabel 必须是非空文本。")
    label = source_label.strip()
    if len(label) > _MAX_LABEL:
        raise SourceMapInvalid(f"sourceLabel 过长（≤{_MAX_LABEL}）。")
    return addr, label


class SourceMapStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def set_map(self, from_addr: Any, source_label: Any) -> dict[str, Any]:
        addr, label = clean_pair(from_addr, source_label)
        await self._db.migrate()
        now = utc_now()
        await self._db.execute(
            "INSERT INTO email_source_maps (from_addr, source_label,"
            " created_at, updated_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(from_addr) DO UPDATE SET"
            " source_label = excluded.source_label,"
            " updated_at = excluded.updated_at",
            (addr, label, now, now),
        )
        return {"fromAddr": addr, "sourceLabel": label}

    async def delete_map(self, from_addr: Any) -> bool:
        if not isinstance(from_addr, str):
            raise SourceMapInvalid("fromAddr 必须是字符串。")
        addr = from_addr.strip().lower()
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT from_addr FROM email_source_maps WHERE from_addr = ?",
            (addr,),
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM email_source_maps WHERE from_addr = ?", (addr,)
        )
        return True

    async def list_maps(self) -> dict[str, Any]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT from_addr, source_label, updated_at FROM email_source_maps"
            " ORDER BY from_addr ASC"
        )
        return {
            "items": [
                {
                    "fromAddr": str(r["from_addr"]),
                    "sourceLabel": str(r["source_label"]),
                    "updatedAt": str(r["updated_at"]),
                }
                for r in rows
            ],
            "honestyNote": HONESTY_NOTE,
        }

    async def addr_map(self) -> dict[str, str]:
        """导入流水线用的 {小写地址 → 来源标签} 快照。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT from_addr, source_label FROM email_source_maps"
        )
        return {str(r["from_addr"]): str(r["source_label"]) for r in rows}
