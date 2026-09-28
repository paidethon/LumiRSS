"""NEW-223 队列工作量预览 —— 按本人阅读速度估算队列时长。

诚实边界（绝不伪造精确耗时）：

- 估时基础 = 投影纯文本长度 ÷ **本人可校正的阅读速度**（单行设置；
  缺省 400 字符/分钟，与 reading_queue 生成用的服务端粗估同源同值，
  但这里是用户显式可改的）。响应恒带 ``basis`` 与「估算，非精确」
  提示；分钟取整向上（ceil）；
- 无投影文本（条目已删/退订/library ref）→ ``minutes=null``，
  计入 ``unknownCount``，绝不瞎猜；
- 压缩范围是**给用户挑的建议清单**（保持全部 / 前半 / 剔除最长 /
  只留短文），服务端只算数字，绝不替用户裁队列。
"""

from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_DEFAULT_SPEED = 400
_MIN_SPEED = 50
_MAX_SPEED = 2000

_MAX_REFS = 200


class WorkloadInvalid(Exception):
    """速度/载荷非法——422 invalid_workload。"""


def validate_speed(chars_per_minute: int) -> int:
    if not isinstance(chars_per_minute, int) or isinstance(chars_per_minute, bool):
        raise WorkloadInvalid("charsPerMinute 必须是整数。")
    if not _MIN_SPEED <= chars_per_minute <= _MAX_SPEED:
        raise WorkloadInvalid(
            f"charsPerMinute 必须在 {_MIN_SPEED}..{_MAX_SPEED} 之间"
            "（人工校正，不是精度表演）。"
        )
    return chars_per_minute


def estimate_minutes(content_text: str | None, chars_per_minute: int) -> int | None:
    """单篇估时：ceil(len/速度)；无文本 → None（诚实未知）。"""
    if content_text is None:
        return None
    length = len(content_text)
    if length == 0:
        return 1
    return max(1, -(-length // chars_per_minute))


class WorkloadStore:
    """Persistence for reading_speed_settings + queue workload estimates."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # -- speed setting ----------------------------------------------------------

    async def get_speed(self) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT chars_per_minute, updated_at FROM reading_speed_settings"
            " WHERE id = 1"
        )
        if row is None:
            return {
                "charsPerMinute": _DEFAULT_SPEED,
                "customized": False,
                "updatedAt": None,
                "note": "缺省粗估 400 字符/分钟；请按自己的实际速度校正。",
            }
        return {
            "charsPerMinute": int(row["chars_per_minute"]),
            "customized": True,
            "updatedAt": str(row["updated_at"]),
            "note": None,
        }

    async def set_speed(self, chars_per_minute: int) -> dict[str, Any]:
        await self._db.migrate()
        validate_speed(chars_per_minute)
        await self._db.execute(
            "INSERT INTO reading_speed_settings (id, chars_per_minute, updated_at)"
            " VALUES (1, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET"
            " chars_per_minute = excluded.chars_per_minute,"
            " updated_at = excluded.updated_at",
            (chars_per_minute, utc_now()),
        )
        return await self.get_speed()

    # -- estimate ---------------------------------------------------------------

    async def estimate(self, refs: list[str]) -> dict[str, Any]:
        """逐篇估时 + 合计（known 合计 + unknownCount 诚实分列）。"""
        await self._db.migrate()
        if not refs or len(refs) > _MAX_REFS:
            raise WorkloadInvalid(f"refs 需为 1..{_MAX_REFS} 条。")
        speed = (await self.get_speed())["charsPerMinute"]
        items: list[dict[str, Any]] = []
        total_known = 0
        unknown = 0
        for item_ref in refs:
            row = await self._db.fetch_one(
                "SELECT title, content_text FROM search_entries"
                " WHERE entry_ref = substr(?, 5)",
                (item_ref,),
            )
            text = row["content_text"] if row is not None else None
            minutes = estimate_minutes(text, speed)
            if minutes is None:
                unknown += 1
            else:
                total_known += minutes
            items.append(
                {
                    "itemRef": item_ref,
                    "title": row["title"] if row is not None else None,
                    "minutes": minutes,
                }
            )
        return {
            "charsPerMinute": speed,
            "items": items,
            "totalKnownMinutes": total_known,
            "unknownCount": unknown,
            "basis": f"ceil(投影纯文本长度 / {speed} 字符每分钟)",
            "note": "估算是数量级参考，不是精确耗时。",
        }

    # -- compression suggestions（建议清单，用户挑） -----------------------------

    async def compressions(self, refs: list[str]) -> dict[str, Any]:
        """给用户挑选的压缩范围建议：全部 / 前半 / 剔除最长 1/4 /
        只留短文（≤ 全体中位数）。纯建议——服务端不裁队列。"""
        estimate = await self.estimate(refs)
        speed = estimate["charsPerMinute"]
        known = [item for item in estimate["items"] if item["minutes"] is not None]
        lengths = sorted(item["minutes"] for item in known)
        n = len(known)
        median = lengths[n // 2] if n else 0
        quarter = max(1, n // 4) if n else 0
        drop_longest = sorted(known, key=lambda item: item["minutes"], reverse=True)[
            :quarter
        ]
        drop_refs = {item["itemRef"] for item in drop_longest}

        def _sum_of(selected: list[dict[str, Any]]) -> int:
            return sum(item["minutes"] for item in selected)

        options: list[dict[str, Any]] = [
            {
                "key": "keep_all",
                "label": "保持全部",
                "refs": [item["itemRef"] for item in estimate["items"]],
                "estimatedMinutes": estimate["totalKnownMinutes"],
            }
        ]
        if n >= 4:
            half = [item["itemRef"] for item in estimate["items"][: n // 2]]
            options.append(
                {
                    "key": "first_half",
                    "label": "只读前一半",
                    "refs": half,
                    "estimatedMinutes": _sum_of(
                        [
                            item
                            for item in estimate["items"][: n // 2]
                            if item["minutes"] is not None
                        ]
                    ),
                }
            )
        if drop_refs:
            kept = [item for item in estimate["items"] if item["itemRef"] not in drop_refs]
            options.append(
                {
                    "key": "drop_longest_quarter",
                    "label": f"剔除最长的 {len(drop_refs)} 篇",
                    "refs": [item["itemRef"] for item in kept],
                    "estimatedMinutes": _sum_of(
                        [item for item in kept if item["minutes"] is not None]
                    ),
                }
            )
            short_only = [
                item for item in estimate["items"]
                if item["minutes"] is not None and item["minutes"] <= median
            ]
            if short_only:
                options.append(
                    {
                        "key": "short_only",
                        "label": f"只留短文（≤ 中位数 {median} 分钟）",
                        "refs": [item["itemRef"] for item in short_only],
                        "estimatedMinutes": _sum_of(short_only),
                    }
                )
        return {
            "charsPerMinute": speed,
            "options": options,
            "basis": estimate["basis"],
            "note": "这些是候选范围，选哪个由你决定；服务端不会替你裁队列。",
        }
