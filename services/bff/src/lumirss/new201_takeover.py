"""NEW-201 订阅接管向导 —— 旧实例导出(OPML) → 现有来源映射 → 确认应用。

语义边界（模块存在的理由）：

- 输入是用户提供的 OPML/导出文件（复用既有 :mod:`lumirss.opml` 的
  安全解析：2 MiB 上界、500 feed 上界、可深嵌套分类）；
- 预演（preview，只读）把导出条目映射到**现有订阅清单**：
  * ``toSubscribe``：导出里有、当前没有的 feed（含 OPML 分类标签）；
  * ``alreadySubscribed``：当前已有的 feed——**绝不重复订阅**（核心
    负向契约），按 FIX-235 同款保守归一化（host 小写/折一个尾斜杠/
    query 逐字符保留）识别同源；分类与当前不同 → ``categoryDiffers``
    如实标注，供用户决定是否随应用「继承目录」（move）；
  * ``invalid``：导出里不可用的 xmlUrl（诚实计数 + 样本）；
- 应用（apply）：只做用户逐项确认过的动作——``subscribe``（新 feed，
  含分类标签）与 ``move``（把已有订阅移入导出的分类=继承目录）；
  逐项结果如实回报（created/skipped_existing/moved/failed），任何单
  项失败不回滚其他项（上游无事务，诚实逐项汇报）；
- 台账：apply 成功后落一行批次台账（含逐项结果），预演零写入。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.opml import OpmlInvalid, OpmlTooLarge, OpmlTooManyFeeds, parse_opml
from lumirss.storage import Database
from lumirss.url_normalize import normalize_feed_url
from lumirss.util import utc_now

MAX_APPLY_ITEMS = 200
ACTIONS = ("subscribe", "move")


class TakeoverInvalid(ValueError):
    """向导输入非法（OPML/动作表），路由层映射 422。"""


class TakeoverBatchNotFound(Exception):
    """台账行不存在 —— 404 takeover_batch_not_found。"""


def parse_opml_or_raise(data: bytes):
    """parse_opml + 异常归一（AdapterError 族 → TakeoverInvalid）。"""
    try:
        return parse_opml(data)
    except (OpmlInvalid, OpmlTooLarge, OpmlTooManyFeeds) as exc:
        raise TakeoverInvalid(str(exc)) from exc


def build_plan(parsed, current_subscriptions: list[Any]) -> dict[str, Any]:
    """导出条目 × 当前订阅 → 接管预览计划（纯函数）。

    ``current_subscriptions`` 是控制适配器清单（feed_url/title/
    category_label）。同源识别用 FIX-235 保守归一化键。"""
    current_by_key: dict[str, Any] = {}
    for sub in current_subscriptions:
        key = normalize_feed_url(str(sub.feed_url))
        if key is not None:
            current_by_key[key] = sub
    to_subscribe: list[dict[str, Any]] = []
    already: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for entry in parsed.entries:
        key = normalize_feed_url(entry.feed_url)
        if key is None:
            continue
        if key in seen_keys:
            continue  # 导出内重复：首现保留（解析器已标注 file_duplicates）
        seen_keys.add(key)
        current = current_by_key.get(key)
        if current is None:
            to_subscribe.append(
                {
                    "feedUrl": entry.feed_url,
                    "title": entry.title or "",
                    "categoryLabel": entry.category_label,
                }
            )
        else:
            current_label = getattr(current, "category_label", None)
            already.append(
                {
                    "feedUrl": entry.feed_url,
                    "opmlTitle": entry.title or "",
                    "currentTitle": getattr(current, "title", "") or "",
                    "opmlCategory": entry.category_label,
                    "currentCategory": current_label,
                    "categoryDiffers": bool(
                        entry.category_label
                        and current_label != entry.category_label
                    ),
                    "subscriptionRef": getattr(current, "subscription_ref", None),
                }
            )
    return {
        "toSubscribe": to_subscribe,
        "alreadySubscribed": already,
        "invalidCount": parsed.invalid_entries,
        "invalidSample": [
            {"feedUrl": item.feed_url, "title": item.title}
            for item in parsed.invalid_items[:10]
        ],
        "exportedTotal": len(parsed.entries) + parsed.invalid_entries,
    }


def validate_apply_items(items: Any) -> list[dict[str, Any]]:
    """校验 apply 动作表（有界 200；动作白名单；键白名单）。"""
    if not isinstance(items, list) or not items:
        raise TakeoverInvalid("items 必须是非空数组。")
    if len(items) > MAX_APPLY_ITEMS:
        raise TakeoverInvalid(f"单批最多 {MAX_APPLY_ITEMS} 项。")
    cleaned: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise TakeoverInvalid(f"第 {index + 1} 项必须是对象。")
        unknown = set(item) - {"action", "feedUrl", "title", "categoryLabel"}
        if unknown:
            raise TakeoverInvalid(f"第 {index + 1} 项含未知键：{sorted(map(str, unknown))}")
        action = item.get("action")
        if action not in ACTIONS:
            raise TakeoverInvalid(f"第 {index + 1} 项的 action 必须是 subscribe/move。")
        feed_url = str(item.get("feedUrl") or "").strip()
        if not feed_url:
            raise TakeoverInvalid(f"第 {index + 1} 项的 feedUrl 不能为空。")
        cleaned.append(
            {
                "action": action,
                "feedUrl": feed_url,
                "title": (str(item.get("title")).strip() or None) if item.get("title") else None,
                "categoryLabel": (
                    str(item.get("categoryLabel")).strip() or None
                )
                if item.get("categoryLabel")
                else None,
            }
        )
    return cleaned


def _row_to_batch(row: Any) -> dict[str, Any]:
    try:
        summary = json.loads(str(row["summary_json"]))
    except (json.JSONDecodeError, TypeError):
        summary = {}
    return {
        "id": str(row["id"]),
        "label": row["label"],
        "summary": summary if isinstance(summary, dict) else {},
        "createdAt": str(row["created_at"]),
    }


class TakeoverStore:
    """应用台账（预演零写入）；inline literal at each execute site。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record_batch(
        self, *, label: str | None, summary: dict[str, Any]
    ) -> dict[str, Any]:
        batch_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO new201_takeover_batches (id, label, summary_json, created_at)"
            " VALUES (?, ?, ?, ?)",
            (batch_id, (label or "").strip() or None, json.dumps(summary, ensure_ascii=False), now),
        )
        return {"id": batch_id, "label": label, "summary": summary, "createdAt": now}

    async def list_batches(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, label, summary_json, created_at FROM new201_takeover_batches"
            " ORDER BY created_at DESC, id DESC LIMIT 50",
            (),
        )
        return [_row_to_batch(row) for row in rows]
