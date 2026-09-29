"""NEW-330 资料路径重定位向导 —— 源目录移动后指向新根，按 content-hash
匹配原条目，避免全部重复导入。

口径：

- 匹配键 = ``parse_note`` 的 content_hash（sha256 原始字节，与主投影
  FIX-337/339 改名侦测完全同口径）；
- 预览（preview）：读新根（containment + 档案忽略规则同款），把新
  布局与档案（obsidian_root_notes）对比 → 五类清单：
  ``relocated``（同哈希唯一匹配、路径变化 → 应用时改 rel_path，行 id
  不变 = 不重复导入）、``inPlace``（同路径同哈希，无需动作）、
  ``fresh``（新哈希 → 下次扫描如实新增）、``vanished``（旧哈希在新根
  找不到）、``ambiguous``（同哈希多候选，绝不瞎猜）；目标路径与既有
  其他行冲突 → ``collision``（排除出应用，诚实列出）；
- 应用（apply）：只做两件事——匹配到的档案行 rel_path 改到新布局 +
  档案根切到新路径；之后一次扫描把 fresh 项如实导入、vanished 项
  如实移除。

per-user：档案与向导记录都在 per-user 库；资料根是 owner 的本地
资料面（路由层 owner 门槛）。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.new325_root_profiles import (
    RootProfileNotFound,
    RootProfileStore,
    walk_root,
)
from lumirss.obsidian import (
    VaultPermissionDenied,
    VaultUnreachable,
    canonical_vault_root,
    parse_note,
)
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_LISTED = 200


class RelocateInvalid(ValueError):
    """重定位输入非法（映射 400）。"""


def _bounded(items: list[Any]) -> list[Any]:
    return items[:_MAX_LISTED]


class RelocationWizard:
    def __init__(self, db: Database, profiles: RootProfileStore) -> None:
        self._db = db
        self._profiles = profiles

    async def preview(self, root_id: str, new_path: str) -> dict[str, Any]:
        profile = await self._profiles.get(root_id)
        if profile is None:
            raise RootProfileNotFound(root_id)
        if not str(new_path or "").strip():
            raise RelocateInvalid("新根路径不能为空。")
        if not profile["authorized"]:
            raise RelocateInvalid("该资料根的授权已撤销，请先重新授权再重定位。")
        try:
            new_root = canonical_vault_root(str(new_path))
        except (VaultUnreachable, VaultPermissionDenied):
            raise
        patterns = [str(p) for p in profile["ignoreGlobs"]]
        files, _skipped_paths, skipped = await _to_thread(walk_root, new_root, patterns)
        new_files: dict[str, str] = {}  # rel_path → content_hash
        hash_counts: dict[str, int] = {}
        for resolved in files:
            note = parse_note(resolved, new_root)
            if note is None:
                continue
            new_files[note["rel_path"]] = note["content_hash"]
            hash_counts[note["content_hash"]] = (
                hash_counts.get(note["content_hash"], 0) + 1
            )
        known_rows = await self._db.fetch_all(
            "SELECT id, rel_path, content_hash FROM obsidian_root_notes WHERE root_id = ?",
            (profile["id"],),
        )
        known = {
            str(row["rel_path"]): {
                "id": str(row["id"]),
                "content_hash": str(row["content_hash"]),
            }
            for row in known_rows
        }
        old_by_hash: dict[str, list[str]] = {}
        for rel, info in known.items():
            old_by_hash.setdefault(info["content_hash"], []).append(rel)
        new_hashes = set(new_files.values())
        relocated: list[dict[str, Any]] = []
        collisions: list[dict[str, str]] = []
        fresh: list[str] = []
        changed: list[str] = []
        ambiguous: list[str] = []
        in_place = 0
        claimed_old: set[str] = set()
        seen_new_hashes: set[str] = set()
        known_rel_paths = set(known)
        for new_rel, new_hash in sorted(new_files.items()):
            if hash_counts.get(new_hash, 0) > 1 or len(
                old_by_hash.get(new_hash, [])
            ) > 1:
                ambiguous.append(new_rel)
                continue
            if new_rel in known:
                if known[new_rel]["content_hash"] == new_hash:
                    in_place += 1
                else:
                    # 同路径但内容已变：既非重定位也非全新导入——下一次
                    # 扫描按 change 如实更新该行（绝不重复导入）。
                    changed.append(new_rel)
                seen_new_hashes.add(new_hash)
                continue
            old_rels = old_by_hash.get(new_hash, [])
            if len(old_rels) == 1 and new_hash not in seen_new_hashes:
                old_rel = old_rels[0]
                if old_rel in known_rel_paths and old_rel not in claimed_old:
                    if new_rel in known_rel_paths:
                        collisions.append(
                            {
                                "from": old_rel,
                                "to": new_rel,
                                "reason": "目标路径已被另一条档案占用。",
                            }
                        )
                    else:
                        relocated.append(
                            {"from": old_rel, "to": new_rel, "id": known[old_rel]["id"]}
                        )
                        claimed_old.add(old_rel)
                        seen_new_hashes.add(new_hash)
                continue
            fresh.append(new_rel)
        vanished = sorted(
            rel
            for rel, info in known.items()
            if info["content_hash"] not in new_hashes
        )
        relocation_id = str(_uuid.uuid4())
        now = utc_now()
        payload = {
            "relocated": _bounded(relocated),
            "fresh": _bounded(fresh),
            "changed": _bounded(changed),
            "vanished": _bounded(vanished),
            "ambiguous": _bounded(ambiguous),
            "collision": _bounded(collisions),
        }

        def _tx(conn: Any) -> None:
            conn.execute(
                "INSERT INTO obsidian_root_relocations (id, root_id, new_path, status,"
                " relocated_json, fresh_json, changed_json, vanished_json, ambiguous_json, collision_json, created_at)"
                " VALUES (?, ?, ?, 'previewed', ?, ?, ?, ?, ?, ?, ?)",
                (
                    relocation_id,
                    profile["id"],
                    str(new_root),
                    json.dumps(payload["relocated"], ensure_ascii=False),
                    json.dumps(payload["fresh"], ensure_ascii=False),
                    json.dumps(payload["changed"], ensure_ascii=False),
                    json.dumps(payload["vanished"], ensure_ascii=False),
                    json.dumps(payload["ambiguous"], ensure_ascii=False),
                    json.dumps(payload["collision"], ensure_ascii=False),
                    now,
                ),
            )

        await transaction(self._db, _tx)
        return {
            "id": relocation_id,
            "rootId": profile["id"],
            "status": "previewed",
            "newPath": str(new_root),
            "inPlaceCount": in_place,
            "skipped": skipped,
            "counts": {
                "relocated": len(payload["relocated"]),
                "fresh": len(payload["fresh"]),
                "changed": len(payload["changed"]),
                "vanished": len(payload["vanished"]),
                "ambiguous": len(payload["ambiguous"]),
                "collision": len(payload["collision"]),
            },
            **payload,
            "honestyNote": "预览零写入；应用只改档案行的路径与根指向（行 id 不变 = 不重复导入），fresh 项由下一次扫描如实新增。",
        }

    async def apply(self, root_id: str, relocation_id: str) -> dict[str, Any]:
        profile = await self._profiles.get(root_id)
        if profile is None:
            raise RootProfileNotFound(root_id)
        row = await self._db.fetch_one(
            "SELECT * FROM obsidian_root_relocations WHERE id = ? AND root_id = ?",
            (str(relocation_id).strip(), profile["id"]),
        )
        if row is None:
            raise RelocateInvalid("重定位记录不存在。")
        if str(row["status"]) != "previewed":
            raise RelocateInvalid("该重定位记录已应用。")
        relocated = _load_list(row["relocated_json"])
        applied = 0
        skipped_collisions: list[dict[str, str]] = []
        now = utc_now()

        def _tx(conn: Any) -> None:
            nonlocal applied
            occupied = {
                str(r["rel_path"])
                for r in conn.execute(
                    "SELECT rel_path FROM obsidian_root_notes WHERE root_id = ?",
                    (profile["id"],),
                ).fetchall()
            }
            for mapping in relocated:
                target = str(mapping.get("to") or "")
                source = str(mapping.get("from") or "")
                row_id = str(mapping.get("id") or "")
                if not target or not row_id or target in occupied:
                    skipped_collisions.append(
                        {"from": source, "to": target, "reason": "目标路径已被占用。"}
                    )
                    continue
                conn.execute(
                    "UPDATE obsidian_root_notes SET rel_path = ?, indexed_at = ? WHERE id = ? AND root_id = ?",
                    (target, now, row_id, profile["id"]),
                )
                occupied.discard(source)
                occupied.add(target)
                applied += 1
            conn.execute(
                "UPDATE obsidian_root_profiles SET root_path = ?, updated_at = ? WHERE id = ?",
                (str(row["new_path"]), now, profile["id"]),
            )
            conn.execute(
                "UPDATE obsidian_root_relocations SET status = 'applied', applied_at = ? WHERE id = ?",
                (now, str(relocation_id).strip()),
            )

        await transaction(self._db, _tx)
        return {
            "id": str(relocation_id).strip(),
            "rootId": profile["id"],
            "status": "applied",
            "appliedAt": now,
            "relocatedApplied": applied,
            "collisionsSkipped": skipped_collisions,
            "newPath": str(row["new_path"]),
            "honestyNote": "档案已指向新根且匹配项按校验和接续（未重复导入）；fresh/vanished 项由下一次扫描如实处理。",
        }

    async def history(self, root_id: str) -> list[dict[str, Any]]:
        profile = await self._profiles.get(root_id)
        if profile is None:
            raise RootProfileNotFound(root_id)
        rows = await self._db.fetch_all(
            "SELECT id, new_path, status, relocated_json, fresh_json, changed_json, vanished_json, ambiguous_json, collision_json, applied_at, created_at"
            " FROM obsidian_root_relocations WHERE root_id = ?"
            " ORDER BY created_at DESC, id DESC LIMIT 50",
            (profile["id"],),
        )
        return [
            {
                "id": str(row["id"]),
                "newPath": str(row["new_path"]),
                "status": str(row["status"]),
                "counts": {
                    "relocated": len(_load_list(row["relocated_json"])),
                    "fresh": len(_load_list(row["fresh_json"])),
                    "changed": len(_load_list(row["changed_json"])),
                    "vanished": len(_load_list(row["vanished_json"])),
                    "ambiguous": len(_load_list(row["ambiguous_json"])),
                    "collision": len(_load_list(row["collision_json"])),
                },
                "appliedAt": row["applied_at"],
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]


def _load_list(raw: Any) -> list[Any]:
    try:
        loaded = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []


async def _to_thread(func: Any, *args: Any) -> Any:
    import asyncio

    return await asyncio.to_thread(func, *args)
