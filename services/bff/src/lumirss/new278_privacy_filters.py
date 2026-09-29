"""NEW-278 AI 输入隐私过滤 —— 用户显式勾选的排除字段 + 过滤差异预览。

诚实口径（硬规则）：

- 过滤 = 显式字段选择：可排除的只有 feedTitle / cachedSummary /
  userNote 三个「辅助上下文」字段（正文不在词表内——AI 任务没有
  正文即无意义）。勾选是行存在；不勾选 = 不过滤；
- 系统绝不声称自动识别所有秘密：过滤只作用于显式勾选的字段，正文
  或笔记里写了什么，服务端不做（也做不了）语义侦测——honestyNote
  随每个响应返回，UI 原样展示；
- 排除在发送路径真实生效（ai_conversation.build_conversation_parts
  的 exclude 参数），不是只在预览里隐藏。

per-user：表在 per-user 库（RoutingDatabase），A 的勾选对 B 不可见。
"""

from typing import Any

from lumirss.ai_conversation import EXCLUDABLE_PARTS
from lumirss.storage import Database
from lumirss.util import utc_now

FIELDS = EXCLUDABLE_PARTS

HONESTY_NOTE = (
    "过滤只作用于你显式勾选的字段；系统不会自动识别正文或笔记中的秘密信息。"
)

_MAX_FIELD_CHARS = 40


class InvalidPrivacyFilter(ValueError):
    """过滤负载非法（映射 422）。"""


def clean_fields(raw: Any) -> list[str]:
    """校验排除清单：必须是 FIELDS 的子集（可空 = 全部不过滤）。"""
    if not isinstance(raw, list):
        raise InvalidPrivacyFilter("exclude 必须是字符串数组。")
    seen: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item:
            raise InvalidPrivacyFilter("exclude 的元素必须是非空字符串。")
        if len(item) > _MAX_FIELD_CHARS:
            raise InvalidPrivacyFilter(f"exclude 字段名过长（≤{_MAX_FIELD_CHARS}）。")
        if item not in FIELDS:
            raise InvalidPrivacyFilter(
                f"未知字段「{item}」；可排除字段：{'、'.join(FIELDS)}。"
            )
        if item not in seen:
            seen.append(item)
    return seen


class PrivacyFilterStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_exclusions(self) -> list[str]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT field FROM ai_privacy_exclusions ORDER BY field ASC"
        )
        return [str(row["field"]) for row in rows if row["field"] in FIELDS]

    async def set_exclusions(self, raw: Any) -> dict[str, Any]:
        """全量替换排除清单（PUT 语义：请求里的清单就是全部勾选）。"""
        clean = clean_fields(raw)
        await self._db.migrate()
        await self._db.execute("DELETE FROM ai_privacy_exclusions")
        now = utc_now()
        for field in clean:
            await self._db.execute(
                "INSERT INTO ai_privacy_exclusions (field, updated_at) VALUES (?, ?)",
                (field, now),
            )
        return self.view(clean)

    def view(self, exclusions: list[str]) -> dict[str, Any]:
        return {
            "exclude": exclusions,
            "fields": list(FIELDS),
            "fieldLabels": {
                "feedTitle": "文章来源",
                "cachedSummary": "AI 摘要（缓存）",
                "userNote": "用户笔记",
            },
            "honestyNote": HONESTY_NOTE,
        }

    async def exclusion_set(self) -> frozenset[str]:
        return frozenset(await self.list_exclusions())


async def filter_diff(
    store: PrivacyFilterStore,
    unfiltered_sections: list[dict[str, Any]],
) -> dict[str, Any]:
    """过滤差异：对一份（未过滤）分段视图给出排除后的对比。

    输入是 new271 预览的 sections JSON；这里按当前排除清单重算
    included，并给出被剔除字符数（诚实：差异来自字段勾选，不是
    内容侦测）。"""
    exclusions = set(await store.list_exclusions())
    removed = 0
    sections: list[dict[str, Any]] = []
    for section in unfiltered_sections:
        item = dict(section)
        key = str(item.get("key") or "")
        if key in exclusions and item.get("included"):
            removed += int(item.get("effectiveChars") or 0)
            item["included"] = False
            item["effectiveChars"] = 0
            item["excludedByFilter"] = True
        sections.append(item)
    return {
        "sections": sections,
        "removedChars": removed,
        "exclude": sorted(exclusions),
        "honestyNote": HONESTY_NOTE,
    }
