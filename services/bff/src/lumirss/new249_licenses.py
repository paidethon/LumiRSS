"""NEW-249 资料引用许可证提示 —— 用户许可证记录 + 汇编导出提示预览。

语义边界（模块存在的理由）：

- license_records：用户为一条资料记录的许可证信息。info_source 区分
  「user_record」（用户自行登记的判断）与「source_explicit」（用户在
  来源页面看到的显式声明）；license_text 为空串 = 明确记录「未声明」；
- 没有记录 = 未知（查询时如实标 unknown，绝不猜默认许可证、绝不
  从标题/来源推断许可证）；
- 提示预览（notice-preview）：给一组 target_refs → 逐条给出
  recorded / explicit_undeclared / unknown 状态 + 汇总文案；输出固定
  附免责声明：「本提示仅转述用户记录与来源明示信息，不构成法律
  意见」。这是转述，不是判断；
- 记录可更新（PUT 覆盖）与撤销（DELETE → 回到 unknown）。

per-user 库：记录天然按账户隔离。
"""

import sqlite3
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now

_TEXT_MAX = 500
_NOTE_MAX = 500
_REF_MAX = 300
_MAX_REFS = 100

_DISCLAIMER = "本提示仅转述你记录的许可证信息与来源页面的明示声明，不构成法律意见。"


class LicenseInvalid(ValueError):
    """许可证记录负载非法（映射 422）。"""


def _clean(value: Any, field: str, *, max_len: int, required: bool, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise LicenseInvalid(f"{field} 必须是字符串。")
    cleaned = value.strip()
    if required and not cleaned:
        raise LicenseInvalid(f"{field} 不能为空。")
    if not required and not cleaned and not allow_empty:
        raise LicenseInvalid(f"{field} 不能为空。")
    if len(cleaned) > max_len:
        raise LicenseInvalid(f"{field} 超出 {max_len} 字符上限。")
    return cleaned


class LicenseRecordStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- 记录 ----------------------------------------------------------------

    async def put_record(
        self, target_ref: str, license_text: str, info_source: str, note: str
    ) -> dict[str, Any]:
        clean_ref = _clean(target_ref, "targetRef", max_len=_REF_MAX, required=True)
        clean_text = _clean(license_text, "licenseText", max_len=_TEXT_MAX, required=False, allow_empty=True)
        if info_source not in ("user_record", "source_explicit"):
            raise LicenseInvalid("infoSource 必须是 user_record 或 source_explicit。")
        clean_note = _clean(note, "note", max_len=_NOTE_MAX, required=False, allow_empty=True)
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            row = conn.execute(
                "SELECT target_ref FROM license_records WHERE target_ref = ?", (clean_ref,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO license_records (target_ref, license_text, info_source, note, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (clean_ref, clean_text, info_source, clean_note, now),
                )
            else:
                conn.execute(
                    "UPDATE license_records SET license_text = ?, info_source = ?, note = ?, updated_at = ? "
                    "WHERE target_ref = ?",
                    (clean_text, info_source, clean_note, now, clean_ref),
                )

        await transaction(self._db, _tx)
        return {
            "targetRef": clean_ref,
            "licenseText": clean_text,
            "infoSource": info_source,
            "note": clean_note,
            "updatedAt": now,
        }

    async def delete_record(self, target_ref: str) -> None:
        clean_ref = _clean(target_ref, "targetRef", max_len=_REF_MAX, required=True)

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM license_records WHERE target_ref = ?", (clean_ref,))

        await transaction(self._db, _tx)

    async def get_record(self, target_ref: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT target_ref, license_text, info_source, note, updated_at "
            "FROM license_records WHERE target_ref = ?",
            (target_ref,),
        )
        return self._record_view(row) if row is not None else self._unknown_view(target_ref)

    async def list_records(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT target_ref, license_text, info_source, note, updated_at "
            "FROM license_records ORDER BY updated_at DESC, target_ref LIMIT 200",
            (),
        )
        return [self._record_view(row) for row in rows]

    # -- 提示预览 --------------------------------------------------------------

    async def notice_preview(self, target_refs: list[str]) -> dict[str, Any]:
        """汇编导出时的引用限制提示（逐条 + 汇总；未知明确标未知）。"""
        if not isinstance(target_refs, list) or not target_refs:
            raise LicenseInvalid("targetRefs 不能为空。")
        if len(target_refs) > _MAX_REFS:
            raise LicenseInvalid(f"单次预览最多 {_MAX_REFS} 条。")
        clean_refs = [_clean(r, "targetRef", max_len=_REF_MAX, required=True) for r in target_refs]
        await self._db.migrate()
        items: list[dict[str, Any]] = []
        unknown_count = 0
        for ref in dict.fromkeys(clean_refs):
            row = await self._db.fetch_one(
                "SELECT target_ref, license_text, info_source, note, updated_at "
                "FROM license_records WHERE target_ref = ?",
                (ref,),
            )
            if row is None:
                unknown_count += 1
                items.append(self._unknown_view(ref))
            else:
                view = self._record_view(row)
                if not view["licenseText"]:
                    unknown_count += 1
                items.append(view)
        return {
            "items": items,
            "unknownCount": unknown_count,
            "disclaimer": _DISCLAIMER,
        }

    # -- 视图 ------------------------------------------------------------------

    @staticmethod
    def _record_view(row: Any) -> dict[str, Any]:
        text = str(row["license_text"])
        if text:
            status = "recorded" if str(row["info_source"]) == "user_record" else "source_explicit"
        else:
            status = "explicit_undeclared"
        return {
            "targetRef": str(row["target_ref"]),
            "status": status,
            "licenseText": text,
            "infoSource": str(row["info_source"]),
            "note": str(row["note"]),
            "updatedAt": str(row["updated_at"]),
        }

    @staticmethod
    def _unknown_view(target_ref: str) -> dict[str, Any]:
        return {
            "targetRef": target_ref,
            "status": "unknown",
            "licenseText": None,
            "infoSource": None,
            "note": "",
            "updatedAt": None,
        }
