"""NEW-325 资料库多根目录档案 —— 每个授权资料根一个独立只读档案。

口径：

- 每个根 = 一个档案行（路径 / 忽略规则 / 授权状态 / 最近扫描状态）+
  独立笔记集（obsidian_root_notes，与主投影 obsidian_notes 解耦）；
- 路径经 :func:`canonical_vault_root` 校验（与主 Vault 同一 containment
  口径：realpath + 每个访问重解析，越界拒绝）；扫描只读，绝不写根；
- 忽略规则（fnmatch glob，如 ``archive/*``）：匹配文件 rel path 或其
  任一父目录 —— 被忽略的子树整枝跳过，不计入档案；
- 增量扫描：fingerprint 命中 → unchanged；fingerprint 变但
  content_hash 相同（移动/mtime 变化）→ 只刷新 fingerprint（行身份
  不变）；否则 changed / added / removed；
- 根数量与每根笔记数有界（20 / 5000），单文件 ≤1MB，.md only。

NEW-329（断开连接）也落在本模块：撤销授权 → 扫描入口拒绝；
副本去留由用户显式二选一（keep / delete），绝不触碰源目录。

per-user：档案在 per-user 库；资料根是 owner 的本地资料面（路由层
owner 门槛），A 的根档案对 B 不可见。
"""

import fnmatch
import json
import uuid as _uuid
from pathlib import Path
from typing import Any

from lumirss.db_tx import transaction
from lumirss.obsidian import (
    VaultPermissionDenied,
    VaultUnreachable,
    _contained,
    canonical_vault_root,
    parse_note,
)
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_ROOTS = 20
MAX_NOTES_PER_ROOT = 5000
MAX_IGNORE_PATTERNS = 20
MAX_IGNORE_PATTERN_LENGTH = 100
_MAX_FILE_BYTES = 1024 * 1024
_MAX_DEPTH = 12


class RootProfileInvalid(ValueError):
    """根档案输入非法（映射 400）。"""


class RootProfileNotFound(Exception):
    """档案不存在（404）。"""


class RootNotAuthorized(Exception):
    """根授权已撤销：扫描入口拒绝（409）。"""


def validate_ignore_globs(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise RootProfileInvalid("ignoreGlobs 必须是字符串数组。")
    patterns: list[str] = []
    for item in raw:
        pattern = str(item).strip()
        if not pattern:
            continue
        if len(pattern) > MAX_IGNORE_PATTERN_LENGTH:
            raise RootProfileInvalid("单条忽略规则 ≤100 字符。")
        if pattern.startswith("/"):
            raise RootProfileInvalid("忽略规则是相对 glob，不能以 / 开头。")
        if pattern not in patterns:
            patterns.append(pattern)
        if len(patterns) > MAX_IGNORE_PATTERNS:
            raise RootProfileInvalid(f"忽略规则最多 {MAX_IGNORE_PATTERNS} 条。")
    return patterns


def _posix_separators(value: str) -> str:
    """FIX-332：反斜杠分隔符 → 正斜杠（忽略规则与 rel_path 同一口径）。"""
    return value.replace("\\", "/")


def is_ignored(rel_path: str, patterns: list[str]) -> bool:
    """rel path 或其任一父目录命中任一 glob → 忽略整枝。

    FIX-332：模式与路径先统一归一到 posix 分隔符再匹配。Windows 书写
    的忽略规则（``archive\\private``）与服务端 walk 产出的 posix
    rel_path 必须命中同一规则；不归一时 posix fnmatch 把 ``\\`` 当转义
    符（``\\*`` = 字面星号），规则静默失效。
    """
    normalized_path = _posix_separators(rel_path)
    parts = normalized_path.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(1, len(parts))]
    for pattern in patterns:
        normalized = _posix_separators(pattern).rstrip("/")
        if not normalized:
            continue
        if fnmatch.fnmatch(normalized_path, normalized):
            return True
        if any(fnmatch.fnmatch(prefix, normalized) for prefix in prefixes):
            return True
    return False


def walk_root(
    root: Path, patterns: list[str]
) -> tuple[list[Path], list[str], int]:
    """有界只读 walk（containment + 忽略规则）。返回 (files, skipped, total_skipped)。"""
    files: list[Path] = []
    skipped_paths: list[str] = []
    skipped = 0
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack and len(files) <= MAX_NOTES_PER_ROOT:
        current, depth = stack.pop()
        if depth > _MAX_DEPTH:
            skipped += 1
            continue
        try:
            entries = sorted(current.iterdir())
        except OSError:
            skipped += 1
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            resolved = _contained(root, entry)
            if resolved is None:
                skipped += 1
                continue
            rel = resolved.relative_to(root).as_posix()
            if is_ignored(rel, patterns):
                skipped += 1
                if len(skipped_paths) < 50:
                    skipped_paths.append(rel)
                continue
            if resolved.is_dir():
                stack.append((resolved, depth + 1))
            elif resolved.suffix.lower() == ".md":
                if len(files) >= MAX_NOTES_PER_ROOT:
                    skipped += 1
                    continue
                try:
                    if resolved.stat().st_size > _MAX_FILE_BYTES:
                        skipped += 1
                        continue
                except OSError:
                    skipped += 1
                    continue
                files.append(resolved)
    files.sort()
    return files, skipped_paths, skipped


def _profile_row(row: Any) -> dict[str, Any]:
    try:
        ignore = json.loads(str(row["ignore_globs_json"] or "[]"))
    except json.JSONDecodeError:
        ignore = []
    try:
        report = json.loads(str(row["last_report_json"] or ""))
    except json.JSONDecodeError:
        report = None
    return {
        "id": str(row["id"]),
        "label": str(row["label"]),
        "rootPath": str(row["root_path"]),
        "ignoreGlobs": ignore if isinstance(ignore, list) else [],
        "authorized": bool(row["authorized"]),
        "copiesPolicy": str(row["copies_policy"] or ""),
        "lastScanAt": row["last_scan_at"],
        "lastError": row["last_error"],
        "lastReport": report if isinstance(report, dict) else None,
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
    }


class RootProfileStore:
    """NEW-325 多根档案 + NEW-329 断开连接（per-user）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    # -- 档案 CRUD ------------------------------------------------------

    async def create(
        self, label: str, root_path: str, ignore_globs: list[str] | None = None
    ) -> dict[str, Any]:
        await self._db.migrate()
        clean_label = str(label or "").strip()[:100]
        if not clean_label:
            raise RootProfileInvalid("档案名称不能为空。")
        patterns = validate_ignore_globs(ignore_globs)
        count_row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM obsidian_root_profiles"
        )
        if count_row is not None and int(count_row["n"]) >= MAX_ROOTS:
            raise RootProfileInvalid(f"资料根档案最多 {MAX_ROOTS} 个。")
        canonical = canonical_vault_root(str(root_path or ""))
        now = utc_now()
        root_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO obsidian_root_profiles (id, label, root_path, ignore_globs_json, authorized, copies_policy, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 1, '', ?, ?)",
            (
                root_id,
                clean_label,
                str(canonical),
                json.dumps(patterns, ensure_ascii=False),
                now,
                now,
            ),
        )
        return await self.get(root_id)  # type: ignore[return-value]

    async def get(self, root_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM obsidian_root_profiles WHERE id = ?",
            (str(root_id).strip(),),
        )
        if row is None:
            return None
        profile = _profile_row(row)
        count_row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM obsidian_root_notes WHERE root_id = ?",
            (profile["id"],),
        )
        profile["noteCount"] = int(count_row["n"]) if count_row is not None else 0
        return profile

    async def list_profiles(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT * FROM obsidian_root_profiles ORDER BY created_at ASC, id ASC LIMIT ?",
            (MAX_ROOTS,),
        )
        profiles = [_profile_row(row) for row in rows]
        for profile in profiles:
            count_row = await self._db.fetch_one(
                "SELECT COUNT(*) AS n FROM obsidian_root_notes WHERE root_id = ?",
                (profile["id"],),
            )
            profile["noteCount"] = (
                int(count_row["n"]) if count_row is not None else 0
            )
        return profiles

    async def update(
        self,
        root_id: str,
        *,
        label: str | None = None,
        ignore_globs: list[str] | None = None,
    ) -> dict[str, Any] | None:
        profile = await self.get(root_id)
        if profile is None:
            return None
        clean_label = (
            profile["label"] if label is None else str(label).strip()[:100]
        )
        if not clean_label:
            raise RootProfileInvalid("档案名称不能为空。")
        patterns = (
            validate_ignore_globs(ignore_globs)
            if ignore_globs is not None
            else profile["ignoreGlobs"]
        )
        await self._db.execute(
            "UPDATE obsidian_root_profiles SET label = ?, ignore_globs_json = ?, updated_at = ? WHERE id = ?",
            (
                clean_label,
                json.dumps(patterns, ensure_ascii=False),
                utc_now(),
                profile["id"],
            ),
        )
        return await self.get(profile["id"])

    async def delete(self, root_id: str) -> bool:
        await self._db.migrate()
        deleted = await self._db.execute(
            "DELETE FROM obsidian_root_profiles WHERE id = ?",
            (str(root_id).strip(),),
        )
        return bool(deleted)

    # -- 扫描（NEW-329：入口校验授权状态）---------------------------------

    async def scan(self, root_id: str) -> dict[str, Any]:
        profile = await self.get(root_id)
        if profile is None:
            raise RootProfileNotFound(root_id)
        if not profile["authorized"]:
            raise RootNotAuthorized(
                f"资料根「{profile['label']}」的授权已撤销，扫描已停止。"
            )
        try:
            root = canonical_vault_root(profile["rootPath"])
        except (VaultUnreachable, VaultPermissionDenied) as exc:
            await self._db.execute(
                "UPDATE obsidian_root_profiles SET last_error = ?, updated_at = ? WHERE id = ?",
                (str(exc)[:500], utc_now(), profile["id"]),
            )
            raise
        patterns = [str(p) for p in profile["ignoreGlobs"]]
        files, skipped_paths, skipped = await _to_thread(walk_root, root, patterns)
        known = {
            str(row["rel_path"]): {
                "id": str(row["id"]),
                "fingerprint": str(row["fingerprint"]),
                "content_hash": str(row["content_hash"]),
            }
            for row in await self._db.fetch_all(
                "SELECT id, rel_path, fingerprint, content_hash FROM obsidian_root_notes WHERE root_id = ?",
                (profile["id"],),
            )
        }
        parsed: dict[str, dict[str, Any]] = {}
        for resolved in files:
            note = parse_note(resolved, root)
            if note is not None:
                parsed[note["rel_path"]] = note
        added = changed = unchanged = 0
        new_rows: list[tuple[str, dict[str, Any]]] = []
        updates: list[tuple[str, dict[str, Any], bool]] = []  # (id, note, hash_only)
        for rel, note in parsed.items():
            existing = known.get(rel)
            if existing is None:
                new_rows.append((str(_uuid.uuid4()), note))
                added += 1
                continue
            if existing["fingerprint"] == note["fingerprint"]:
                unchanged += 1
                continue
            hash_only = existing["content_hash"] == note["content_hash"]
            updates.append((existing["id"], note, hash_only))
            changed += 1
        removed_ids = [
            known[rel]["id"] for rel in set(known) - set(parsed)
        ]
        removed = len(removed_ids)
        now = utc_now()
        report = {
            "added": added,
            "changed": changed,
            "removed": removed,
            "unchanged": unchanged,
            "skipped": skipped,
            "skippedPaths": skipped_paths[:50],
        }

        def _tx(conn: Any) -> None:
            for row_id, note in new_rows:
                conn.execute(
                    "INSERT INTO obsidian_root_notes (id, root_id, rel_path, fingerprint, content_hash, title, tags_json, indexed_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row_id,
                        profile["id"],
                        note["rel_path"],
                        note["fingerprint"],
                        note["content_hash"],
                        note["title"],
                        json.dumps(note["tags"], ensure_ascii=False),
                        now,
                    ),
                )
            for row_id, note, hash_only in updates:
                if hash_only:
                    conn.execute(
                        "UPDATE obsidian_root_notes SET fingerprint = ?, indexed_at = ? WHERE id = ?",
                        (note["fingerprint"], now, row_id),
                    )
                else:
                    conn.execute(
                        "UPDATE obsidian_root_notes SET fingerprint = ?, content_hash = ?, title = ?, tags_json = ?, indexed_at = ? WHERE id = ?",
                        (
                            note["fingerprint"],
                            note["content_hash"],
                            note["title"],
                            json.dumps(note["tags"], ensure_ascii=False),
                            now,
                            row_id,
                        ),
                    )
            for row_id in removed_ids:
                conn.execute(
                    "DELETE FROM obsidian_root_notes WHERE id = ?", (row_id,)
                )
            conn.execute(
                "UPDATE obsidian_root_profiles SET last_scan_at = ?, last_error = NULL,"
                " last_report_json = ?, updated_at = ? WHERE id = ?",
                (
                    now,
                    json.dumps(report, ensure_ascii=False),
                    now,
                    profile["id"],
                ),
            )

        await transaction(self._db, _tx)
        return {**report, "rootId": profile["id"], "scannedAt": now}

    async def notes(self, root_id: str, tag: str = "") -> list[dict[str, Any]]:
        profile = await self.get(root_id)
        if profile is None:
            raise RootProfileNotFound(root_id)
        rows = await self._db.fetch_all(
            "SELECT id, rel_path, title, tags_json, content_hash, indexed_at FROM obsidian_root_notes"
            " WHERE root_id = ? ORDER BY rel_path ASC LIMIT ?",
            (profile["id"], MAX_NOTES_PER_ROOT),
        )
        want_tag = tag.strip()
        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                tags = json.loads(str(row["tags_json"] or "[]"))
            except json.JSONDecodeError:
                tags = []
            tags = [str(t) for t in tags] if isinstance(tags, list) else []
            if want_tag and want_tag not in tags:
                continue
            items.append(
                {
                    "id": str(row["id"]),
                    "relPath": str(row["rel_path"]),
                    "title": str(row["title"]),
                    "tags": tags,
                    "contentHash": str(row["content_hash"]),
                    "indexedAt": str(row["indexed_at"]),
                }
            )
        return items

    # -- NEW-329：断开连接 / 副本去留 / 重新授权 -------------------------

    async def disconnect(self, root_id: str) -> dict[str, Any]:
        """撤销授权：扫描入口从此拒绝（调度/扫描入口都校验）。

        副本去留【不在此决定】——保持当前状态，等用户显式选择
        keep / delete；之前未扫描过的根 copies_policy 为 ''。"""
        profile = await self.get(root_id)
        if profile is None:
            raise RootProfileNotFound(root_id)
        await self._db.execute(
            "UPDATE obsidian_root_profiles SET authorized = 0, updated_at = ? WHERE id = ?",
            (utc_now(), profile["id"]),
        )
        result = await self.get(profile["id"])
        assert result is not None
        return result

    async def decide_copies(self, root_id: str, action: str) -> dict[str, Any]:
        """用户显式选择：保留导入副本（kept）或删除本应用副本（deleted）。

        delete 只清 Lumi 侧档案笔记（obsidian_root_notes），绝不触碰
        源目录。幂等：重复选择同一动作返回相同状态（removed=0）。"""
        profile = await self.get(root_id)
        if profile is None:
            raise RootProfileNotFound(root_id)
        clean = str(action or "").strip()
        if clean not in ("keep", "delete"):
            raise RootProfileInvalid("action 必须是 keep 或 delete。")
        removed = 0
        if clean == "delete":
            result = await self._db.execute(
                "DELETE FROM obsidian_root_notes WHERE root_id = ?",
                (profile["id"],),
            )
            removed = int(result or 0)
        await self._db.execute(
            "UPDATE obsidian_root_profiles SET copies_policy = ?, updated_at = ? WHERE id = ?",
            ("kept" if clean == "keep" else "deleted", utc_now(), profile["id"]),
        )
        return {
            "rootId": profile["id"],
            "action": clean,
            "copiesPolicy": "kept" if clean == "keep" else "deleted",
            "removedCopies": removed,
        }

    async def reconnect(self, root_id: str) -> dict[str, Any]:
        """重新授权（扫描恢复）；副本若曾被删除，下次扫描如实全新导入。"""
        profile = await self.get(root_id)
        if profile is None:
            raise RootProfileNotFound(root_id)
        await self._db.execute(
            "UPDATE obsidian_root_profiles SET authorized = 1, updated_at = ? WHERE id = ?",
            (utc_now(), profile["id"]),
        )
        result = await self.get(profile["id"])
        assert result is not None
        return result


async def _to_thread(func: Any, *args: Any) -> Any:
    import asyncio

    return await asyncio.to_thread(func, *args)
