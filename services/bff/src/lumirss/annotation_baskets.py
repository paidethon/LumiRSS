"""N072 批注精选篮 —— 跨篇手工挑选的批注集合（存储层）。

- 篮只存批注引用（annotation_id），不 shadow-copy 批注本体；
- 加入幂等（复合主键；重复加入不产生副本、不报错）；
- 批注本体被删除后成员行如实保留，读取侧标 broken=true（与锚点
  stale 同一诚实口径：篮导出/回跳绝不假装成员还健在）；
- per-user 库：篮与成员物理隔离，跨用户不可见。

SQL 直写站点 4 处（INSERT basket / INSERT item(s) / UPDATE name /
DELETE 篮级联）+ 成员删除 1 处——量小聚在本文件，避免撑爆
annotation_store.py 的单文件职责。
"""

import uuid as _uuid
from typing import Any

from lumirss.annotation_store import AnnotationStore
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_NAME = 100
MAX_BASKETS = 50
MAX_ADD_BATCH = 200


class BasketInvalid(ValueError):
    """篮负载非法（名字为空/过长、批注 id 缺失等），映射 422。"""


class BasketNotFound(LookupError):
    """篮不存在（或已删除），映射 404。"""


def _row_to_basket(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": str(row["name"]),
        "createdAt": str(row["created_at"]),
    }


class AnnotationBasketStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---- 篮 CRUD ---------------------------------------------------------

    async def create(self, *, name: str) -> dict[str, Any]:
        clean = str(name or "").strip()
        if not clean:
            raise BasketInvalid("篮名称不能为空。")
        if len(clean) > MAX_NAME:
            raise BasketInvalid(f"篮名称过长（≤{MAX_NAME} 字符）。")
        await self._db.migrate()
        count_row = await self._db.fetch_one("SELECT COUNT(*) AS n FROM annotation_baskets")
        if count_row is not None and int(count_row["n"]) >= MAX_BASKETS:
            raise BasketInvalid(f"精选篮最多 {MAX_BASKETS} 个。")
        basket_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO annotation_baskets (id, name, created_at) VALUES (?, ?, ?)",
            (basket_id, clean, now),
        )
        return {"id": basket_id, "name": clean, "createdAt": now}

    async def list_baskets(self) -> list[dict[str, Any]]:
        """全部篮（旧→新），附真实成员计数（含 broken——计数是成员行
        计数，不是「健在批注」计数，诚实口径）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT b.id, b.name, b.created_at,"
            " (SELECT COUNT(*) FROM annotation_basket_items i WHERE i.basket_id = b.id) AS item_count"
            " FROM annotation_baskets b ORDER BY b.created_at ASC, b.id ASC"
        )
        return [
            {**_row_to_basket(row), "itemCount": int(row["item_count"])}
            for row in rows
        ]

    async def rename(self, basket_id: str, *, name: str) -> dict[str, Any] | None:
        clean = str(name or "").strip()
        if not clean:
            raise BasketInvalid("篮名称不能为空。")
        if len(clean) > MAX_NAME:
            raise BasketInvalid(f"篮名称过长（≤{MAX_NAME} 字符）。")
        await self._db.migrate()
        changed = await self._db.execute(
            "UPDATE annotation_baskets SET name = ? WHERE id = ?", (clean, basket_id)
        )
        if not changed:
            return None
        row = await self._db.fetch_one(
            "SELECT id, name, created_at FROM annotation_baskets WHERE id = ?", (basket_id,)
        )
        return _row_to_basket(row) if row is not None else None

    async def delete(self, basket_id: str) -> bool:
        """删篮（成员关系级联删除；批注本体绝不动）。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM annotation_baskets WHERE id = ?", (basket_id,)
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM annotation_basket_items WHERE basket_id = ?", (basket_id,)
        )
        await self._db.execute("DELETE FROM annotation_baskets WHERE id = ?", (basket_id,))
        return True

    # ---- 成员 ---------------------------------------------------------

    async def basket_exists(self, basket_id: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT 1 AS x FROM annotation_baskets WHERE id = ?", (basket_id,)
        )
        return row is not None

    async def add_items(self, basket_id: str, annotation_ids: list[str]) -> dict[str, Any]:
        """批量加入（幂等）。不存在的批注 id 逐个 honest 拒绝（整批里
        只有真实存在的批注入篮，返回 added/skipped 明细）。"""
        clean_ids = [str(aid).strip() for aid in annotation_ids if str(aid).strip()]
        if not clean_ids:
            raise BasketInvalid("annotationIds 不能为空。")
        if len(clean_ids) > MAX_ADD_BATCH:
            raise BasketInvalid(f"每批最多加入 {MAX_ADD_BATCH} 条批注。")
        await self._db.migrate()
        if not await self.basket_exists(basket_id):
            raise BasketNotFound(basket_id)
        annotations = AnnotationStore(self._db)
        now = utc_now()
        added: list[str] = []
        skipped: list[dict[str, str]] = []
        for annotation_id in dict.fromkeys(clean_ids):  # 去重保序
            item = await annotations.get(annotation_id)
            if item is None:
                skipped.append({"annotationId": annotation_id, "reason": "annotation_not_found"})
                continue
            existing = await self._db.fetch_one(
                "SELECT 1 AS x FROM annotation_basket_items WHERE basket_id = ? AND annotation_id = ?",
                (basket_id, annotation_id),
            )
            if existing is not None:
                skipped.append({"annotationId": annotation_id, "reason": "already_member"})
                continue
            await self._db.execute(
                "INSERT INTO annotation_basket_items (basket_id, annotation_id, added_at) VALUES (?, ?, ?)",
                (basket_id, annotation_id, now),
            )
            added.append(annotation_id)
        return {"added": added, "skipped": skipped}

    async def remove_item(self, basket_id: str, annotation_id: str) -> bool:
        await self._db.migrate()
        changed = await self._db.execute(
            "DELETE FROM annotation_basket_items WHERE basket_id = ? AND annotation_id = ?",
            (basket_id, annotation_id),
        )
        return bool(changed)

    async def list_items(self, basket_id: str) -> list[dict[str, Any]]:
        """篮成员（加入顺序旧→新），连接批注本体；批注已删除 →
        broken=true（成员行保留，供「原文已变化/已删除」诚实展示）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT i.annotation_id, i.added_at FROM annotation_basket_items i"
            " WHERE i.basket_id = ? ORDER BY i.added_at ASC, i.rowid ASC",
            (basket_id,),
        )
        annotations = AnnotationStore(self._db)
        items: list[dict[str, Any]] = []
        for row in rows:
            annotation_id = str(row["annotation_id"])
            annotation = await annotations.get(annotation_id)
            if annotation is None:
                items.append(
                    {
                        "annotationId": annotation_id,
                        "addedAt": str(row["added_at"]),
                        "broken": True,
                        "annotation": None,
                    }
                )
                continue
            items.append(
                {
                    "annotationId": annotation_id,
                    "addedAt": str(row["added_at"]),
                    "broken": bool((annotation.get("anchor") or {}).get("stale")),
                    "annotation": annotation,
                }
            )
        return items

    async def member_ids(self, basket_id: str) -> set[str]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT annotation_id FROM annotation_basket_items WHERE basket_id = ?",
            (basket_id,),
        )
        return {str(row["annotation_id"]) for row in rows}
