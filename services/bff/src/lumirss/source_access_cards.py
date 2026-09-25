"""N019 来源接入说明卡 —— per-feed 结构化接入元数据（SQL 唯一入口）。

与 F005 source_notes（自由文本）互补：接入说明卡是**结构化字段**，
供来源设置对话框渲染成卡片：

- ``acquisition``（获取方式）：这个来源的内容是怎么来的（RSSHub
  路由参数、API 来源、邮件桥等）；
- ``limits``（站点限制）：上游站点的频率限制 / 反爬注意事项；
- ``credentialOwnership``（凭据归属）：``self``（本账号）| ``shared``
  （共享）| ``none``（无凭据）——**只存归属标签，绝不存凭据值**：
  schema 没有 secret 字段（见迁移 0117 注释），凭据值属于 RSSHub
  凭据库等既有 write-only 边界；
- ``maintenance``（维护说明）：坏了该找谁 / 怎么修。

存原文（不消毒），渲染转义是 Web 层职责（React 默认转义）；字段
键集合在写入前白名单校验（未知键拒绝），文本有界截断。per-user
库隔离保证用户只看到自己的卡。
"""

import json
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

# 结构化字段白名单（多余键拒绝 —— 契约上就不存在 secret 字段）。
CARD_FIELDS = ("acquisition", "limits", "credentialOwnership", "maintenance")

# 凭据归属只允许这三个归属标签（中文标签由 Web 渲染层映射）。
CREDENTIAL_OWNERSHIP_VALUES = ("self", "shared", "none")

_TEXT_BOUND = 2000  # 有界：单字段超长截断（诚实有界，非无限存储）


class AccessCardInvalid(ValueError):
    """卡片载荷非法（未知键 / 归属标签越界）——路由层映射 422。"""


def validate_card_fields(raw: Any) -> dict[str, Any]:
    """白名单校验：未知键拒绝（AccessCardInvalid），文本有界截断。

    返回 None 值键已剔除的干净 dict；空 dict 合法（= 清空卡片）。"""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise AccessCardInvalid("fields 必须是对象。")
    unknown = set(raw) - set(CARD_FIELDS)
    if unknown:
        raise AccessCardInvalid(f"接入说明卡含未知字段：{sorted(unknown)}")
    clean: dict[str, Any] = {}
    for key in CARD_FIELDS:
        value = raw.get(key)
        if value is None:
            continue
        if key == "credentialOwnership":
            if value not in CREDENTIAL_OWNERSHIP_VALUES:
                raise AccessCardInvalid(
                    "credentialOwnership 必须是 'self'、'shared' 或 'none'。"
                )
            clean[key] = value
            continue
        if not isinstance(value, str):
            raise AccessCardInvalid(f"{key} 必须是字符串或 null。")
        text = value.strip()
        if text:
            clean[key] = text[:_TEXT_BOUND]
    return clean


class SourceAccessCardStore:
    """CRUD over source_access_cards（bounded table：每 feed 至多一行）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_card(self, feed_url: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT feed_url, fields_json, updated_at FROM source_access_cards WHERE feed_url = ?",
            (feed_url,),
        )
        if row is None:
            return {
                "feedUrl": feed_url,
                "acquisition": None,
                "limits": None,
                "credentialOwnership": None,
                "maintenance": None,
                "updatedAt": None,
            }
        return {"feedUrl": feed_url, **self._parse_fields(row["fields_json"]), "updatedAt": str(row["updated_at"] or "")}

    async def put_card(
        self, feed_url: str, fields: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Upsert 整卡（fields = 校验后的干净 dict；空 = 清空）。

        整卡语义（非逐字段 sentinel）：编辑器一次提交完整表单，
        缺席字段 = 清空该字段——比半更新的 sentinel 更可预期。"""
        clean = validate_card_fields(fields)
        await self._db.migrate()
        if not clean:
            await self._db.execute(
                "DELETE FROM source_access_cards WHERE feed_url = ?",
                (feed_url,),
            )
            return await self.get_card(feed_url)
        payload = json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
        await self._db.execute(
            "INSERT INTO source_access_cards (feed_url, fields_json, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(feed_url) DO UPDATE SET fields_json = excluded.fields_json, updated_at = excluded.updated_at",
            (feed_url, payload, utc_now()),
        )
        return await self.get_card(feed_url)

    async def list_cards(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT feed_url, fields_json, updated_at FROM source_access_cards ORDER BY updated_at DESC"
        )
        return [
            {"feedUrl": str(row["feed_url"]), **self._parse_fields(row["fields_json"]), "updatedAt": str(row["updated_at"] or "")}
            for row in rows
        ]

    @staticmethod
    def _parse_fields(raw: Any) -> dict[str, Any]:
        """fields_json → 展平的卡片字段（损坏 JSON 诚实降级全 None）。"""
        try:
            parsed = json.loads(str(raw))
        except (ValueError, TypeError):
            return {field: None for field in CARD_FIELDS}
        if not isinstance(parsed, dict):
            return {field: None for field in CARD_FIELDS}
        return {
            field: (
                parsed[field]
                if isinstance(parsed.get(field), str) and parsed[field]
                else parsed.get(field)
            )
            for field in CARD_FIELDS
        }
