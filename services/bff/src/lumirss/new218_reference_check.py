"""NEW-218 资料引用关系检查 —— 指向已删除（不可解析）文章的引用清单。

检查面（全部 per-user 本地表，候选每面有界 200）：
- 集合条目 workspace_items.item_ref；
- 手工关联 item_relations.src_ref / dst_ref；
- 阅读便签 reading_notes.entry_ref。

判定：经 Source Registry 解析（投影优先，rss 投影未命中才触上游，
测试/降级环境 adapter=None 时确定性 stale），不可解析即失效引用。
用户可以：
- relink：把该引用改指新目标（格式校验 + ensure_resolvable——新目标
  必须真实存在；目标已被占用 → 409）；
- keep-stale：登记「保留失效标记」，检查器跳过（可解除）。
绝不自动删除任何引用——失效是信息，删除永远是显式用户动作。
"""

import asyncio
import sqlite3
from typing import Any

from lumirss.db_tx import transaction
from lumirss.itemref import parse_item_ref
from lumirss.sources import ItemRefUnresolvable, ensure_resolvable
from lumirss.storage import Database
from lumirss.util import utc_now

_CANDIDATES_PER_SURFACE = 200
_CHECK_BOUND = 300
_RESOLVE_CONCURRENCY = 8

_SURFACES = ("workspaces", "relations", "notes")


class ReferenceCheckInvalid(ValueError):
    """检查/重关联载荷非法（域词表/引用形状/定位），映射 422。"""


class ReferenceCheckConflict(Exception):
    """重关联目标冲突（唯一索引占用），映射 409。"""


class ReferenceCheckStore:
    """DB 侧：候选收集、keep 登记、relink 的域内改写。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def candidates(self, surfaces: list[str]) -> list[dict[str, Any]]:
        await self._db.migrate()
        return await transaction(self._db, lambda conn: _collect_candidates(conn, surfaces))

    async def kept_stale(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, domain_name, locator, ref, marked_at FROM new218_stale_keeps ORDER BY id DESC LIMIT 500"
        )
        return [
            {
                "id": int(r["id"]),
                "surface": str(r["domain_name"]),
                "locator": str(r["locator"]),
                "ref": str(r["ref"]),
                "markedAt": str(r["marked_at"]),
            }
            for r in rows
        ]

    async def keep_stale(self, surface: str, locator: str, ref: str) -> dict[str, Any]:
        if surface not in _SURFACES:
            raise ReferenceCheckInvalid(f"未知检查面：{surface}。")
        clean = parse_item_ref(ref).format()
        await self._db.migrate()
        existing = await self._db.fetch_one(
            "SELECT id FROM new218_stale_keeps WHERE domain_name = ? AND locator = ? AND ref = ?",
            (surface, locator, clean),
        )
        if existing is not None:
            return {"id": int(existing["id"]), "kept": True, "already": True}
        await self._db.execute(
            "INSERT INTO new218_stale_keeps (domain_name, locator, ref, marked_at) VALUES (?, ?, ?, ?)",
            (surface, locator, clean, utc_now()),
        )
        return {"kept": True, "already": False}

    async def unkeep_stale(self, keep_id: int) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT id FROM new218_stale_keeps WHERE id = ?", (keep_id,))
        if row is None:
            return False
        await self._db.execute("DELETE FROM new218_stale_keeps WHERE id = ?", (keep_id,))
        return True

    async def relink(
        self, surface: str, locator: str, old_ref: str, new_ref: str
    ) -> dict[str, Any]:
        if surface not in _SURFACES:
            raise ReferenceCheckInvalid(f"未知检查面：{surface}。")
        clean_old = parse_item_ref(old_ref).format()
        clean_new = parse_item_ref(new_ref).format()
        await self._db.migrate()

        def _relink(conn: sqlite3.Connection) -> dict[str, Any]:
            conn.execute("BEGIN IMMEDIATE")
            if surface == "workspaces":
                cur = conn.execute(
                    "UPDATE workspace_items SET item_ref = ? WHERE workspace_id = ? AND item_ref = ?",
                    (clean_new, locator, clean_old),
                )
            elif surface == "notes":
                cur = conn.execute(
                    "UPDATE reading_notes SET entry_ref = ? WHERE entry_ref = ?",
                    (clean_new, clean_old),
                )
            else:
                relation_id, side = _parse_relation_locator(locator)
                if side == "src":
                    cur = conn.execute(
                        "UPDATE item_relations SET src_ref = ? WHERE id = ? AND src_ref = ?",
                        (clean_new, relation_id, clean_old),
                    )
                else:
                    cur = conn.execute(
                        "UPDATE item_relations SET dst_ref = ? WHERE id = ? AND dst_ref = ?",
                        (clean_new, relation_id, clean_old),
                    )
            moved = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            return {
                "moved": moved,
                "surface": surface,
                "locator": locator,
                "from": clean_old,
                "to": clean_new,
            }

        try:
            result = await transaction(self._db, _relink)
        except sqlite3.IntegrityError as exc:
            raise ReferenceCheckConflict("目标引用已存在（唯一约束）。") from exc
        if int(result["moved"]) == 0:
            raise ReferenceCheckInvalid("没有找到要重关联的引用（可能已被处理）。")
        return result


def _parse_relation_locator(locator: str) -> tuple[int, str]:
    text, _, side = locator.rpartition(":")
    if side not in ("src", "dst") or not text.isdigit():
        raise ReferenceCheckInvalid(f"关联定位非法：{locator}")
    return int(text), side


def _collect_candidates(conn: sqlite3.Connection, surfaces: list[str]) -> list[dict[str, Any]]:
    """有界候选收集（单连接只读）。"""
    candidates: list[dict[str, Any]] = []
    if "workspaces" in surfaces:
        for row in conn.execute(
            "SELECT workspace_id, item_ref FROM workspace_items ORDER BY workspace_id, position LIMIT ?",
            (_CANDIDATES_PER_SURFACE,),
        ):
            candidates.append(
                {"surface": "workspaces", "locator": str(row["workspace_id"]), "ref": str(row["item_ref"])}
            )
    if "relations" in surfaces:
        for row in conn.execute(
            "SELECT id, src_ref, dst_ref FROM item_relations ORDER BY id LIMIT ?",
            (_CANDIDATES_PER_SURFACE,),
        ):
            candidates.append({"surface": "relations", "locator": f"{row['id']}:src", "ref": str(row["src_ref"])})
            candidates.append({"surface": "relations", "locator": f"{row['id']}:dst", "ref": str(row["dst_ref"])})
    if "notes" in surfaces:
        for row in conn.execute(
            "SELECT entry_ref FROM reading_notes ORDER BY entry_ref LIMIT ?",
            (_CANDIDATES_PER_SURFACE,),
        ):
            candidates.append({"surface": "notes", "locator": "reading_note", "ref": str(row["entry_ref"])})
    return candidates


async def check_references(db: Database, registry: dict, surfaces: list[str]) -> dict[str, Any]:
    """候选解析（投影优先；并发有界）→ 失效清单 + 已保留清单。"""
    store = ReferenceCheckStore(db)
    candidates = await store.candidates(surfaces)
    kept = {(k["surface"], k["locator"], k["ref"]) for k in await store.kept_stale()}
    distinct_refs = list({c["ref"] for c in candidates})[:_CHECK_BOUND]
    semaphore = asyncio.Semaphore(_RESOLVE_CONCURRENCY)

    async def _dangling(ref: str) -> bool:
        try:
            async with semaphore:
                resolved = await ensure_resolvable(registry, ref)
            return resolved.kind == "unknown"
        except ItemRefUnresolvable:
            return True
        except ValueError:
            return True  # 形状非法的引用视同失效（诚实上报，绝不静默吞）

    results = await asyncio.gather(*(_dangling(ref) for ref in distinct_refs))
    dangling_refs = {ref for ref, is_dangling in zip(distinct_refs, results, strict=True) if is_dangling}
    issues = [
        {"surface": c["surface"], "locator": c["locator"], "ref": c["ref"]}
        for c in candidates
        if c["ref"] in dangling_refs and (c["surface"], c["locator"], c["ref"]) not in kept
    ]
    kept_items = [
        {"surface": c["surface"], "locator": c["locator"], "ref": c["ref"]}
        for c in candidates
        if c["ref"] in dangling_refs and (c["surface"], c["locator"], c["ref"]) in kept
    ]
    return {
        "checked": len(distinct_refs),
        "issues": issues[:_CHECK_BOUND],
        "keptStale": kept_items,
        "truncated": len(candidates) >= _CANDIDATES_PER_SURFACE * len(surfaces),
    }
