"""Obsidian read-only vault projection (phase2 G6 + recovery Gate 4).

The user's vault is the source of truth; this module only READS it and
maintains a derived, rebuildable projection (obsidian_notes rows +
search_library). Hard guarantees:

- deployment contract: under production Compose the vault arrives as a
  read-only bind mount at a FIXED container path (``LUMIRSS_OBSIDIAN_
  VAULT_DIR``); host paths never reach the BFF. When the env root is
  set, the DB-configured path is ignored and cannot be changed via API.
- containment: the vault root is canonicalized once per scan (realpath);
  EVERY file access re-resolves and refuses anything outside the root —
  symlinks/junctions/bind-mounts to outside paths are excluded, not
  followed;
- read-only: no write/rename/mkdir/unlink call exists in this module;
- bounded: .md only, files >1MB skipped, null-byte binary sniff, depth
  and file-count caps, per-file parse errors degrade to "unparsable"
  rows instead of failing the scan;
- rename detection: a rename is adopted ONLY when exactly one removed
  path carries the new file's content hash — two files with identical
  content are two notes, never a rename (P0-09g);
- one scan batch = one transaction (library_items + obsidian_notes +
  search projection commit or roll back together, P0-09h);
- truncation is explicit: notes over the bounded-projection caps carry
  ``truncated=1`` and the report counts them (P0-09d);
- note views render the INDEXED snapshot, so body, tags, wikilinks and
  html can never disagree with each other (P0-09f).
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frontmatter as fm_module

from lumirss.itemref import new_library_uuid
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_FILE_BYTES = 1024 * 1024
_MAX_FILES = 20000
_MAX_DEPTH = 12
_MAX_TAG_LENGTH = 50
_MAX_TITLE_LENGTH = 500
_MAX_WIKILINKS = 100
_MAX_BODY_LENGTH = 20000
# NEW-327：frontmatter 属性投影上限（键值均字符串化、有界）——列表列
# 映射的数据源。绝不回写文件，原格式保持不变。
_MAX_PROPERTIES = 20
_MAX_PROPERTY_KEY = 50
_MAX_PROPERTY_VALUE = 200
# N138：文件级诊断列表每类最多列出的路径数（超出 → truncated 标志）。
_MAX_LISTED_PATHS = 50

_logger = logging.getLogger("lumirss.obsidian")


class VaultUnreachable(Exception):
    """The configured vault path does not exist or is not a directory."""


class VaultPermissionDenied(Exception):
    """The vault path cannot be read (OS permission)."""


class VaultRootLocked(Exception):
    """The API cannot change the vault root while the env fixes it."""


class NoteNotFound(Exception):
    """No projected note exists under the requested uuid (404, not a
    vault problem — the indexed snapshot renders without the vault)."""


@dataclass(frozen=True)
class ScanReport:
    added: int
    changed: int
    removed: int
    renames: int
    unchanged: int
    skipped: int
    truncated_notes: int
    elapsed_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "changed": self.changed,
            "removed": self.removed,
            "renames": self.renames,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
            "truncatedNotes": self.truncated_notes,
            "elapsedMs": self.elapsed_ms,
        }


def _bounded_paths(paths: list[str]) -> dict[str, Any]:
    """N138：路径列表有界化（≤_MAX_LISTED_PATHS 条 + truncated 标志）。"""
    unique: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return {
        "items": unique[:_MAX_LISTED_PATHS],
        "truncated": len(unique) > _MAX_LISTED_PATHS,
    }


def build_scan_files_report(
    *,
    added: list[str],
    changed: list[str],
    removed: list[str],
    skipped: list[str],
) -> dict[str, Any]:
    """N138：文件级诊断报告（新增/更改/删除/跳过，各类有界 + 截断标志）。"""
    return {
        "added": _bounded_paths(added),
        "changed": _bounded_paths(changed),
        "removed": _bounded_paths(removed),
        "skipped": _bounded_paths(skipped),
    }


def canonical_vault_root(vault_path: str) -> Path:
    """Canonical realpath of the configured vault; honest errors."""
    if not vault_path or not vault_path.strip():
        raise VaultUnreachable("未配置 Vault 路径。")
    try:
        root = Path(vault_path.strip()).expanduser().resolve(strict=True)
    except FileNotFoundError as exc:
        raise VaultUnreachable("Vault 路径不存在。") from exc
    except OSError as exc:
        raise VaultPermissionDenied("Vault 路径无法访问。") from exc
    if not root.is_dir():
        raise VaultUnreachable("Vault 路径不是目录。")
    return root


def _contained(root: Path, candidate: Path) -> Path | None:
    """Re-resolve and refuse anything outside root (symlink escape etc.)."""
    try:
        resolved = candidate.resolve()
        if resolved == root or root in resolved.parents:
            return resolved
    except OSError:
        return None
    return None


def _iter_markdown_files(root: Path) -> tuple[list[Path], list[str], int]:
    """Bounded walk; symlink escapes excluded.

    Returns (files, skipped_paths, skipped_total) — skipped_paths is the
    bounded, displayable list (N138 diagnostics; ≤_MAX_LISTED_PATHS entries,
    the caller reports the honest total via skipped_total).
    """
    files: list[Path] = []
    skipped_paths: list[str] = []
    skipped = 0
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack and len(files) <= _MAX_FILES:
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
                if len(skipped_paths) < _MAX_LISTED_PATHS:
                    skipped_paths.append(_rel_for_display(root, entry))
                continue
            if resolved.is_dir():
                stack.append((resolved, depth + 1))
            elif resolved.suffix.lower() == ".md":
                if len(files) >= _MAX_FILES:
                    skipped += 1
                    if len(skipped_paths) < _MAX_LISTED_PATHS:
                        skipped_paths.append(_rel_for_display(root, resolved))
                    continue
                try:
                    if resolved.stat().st_size > _MAX_FILE_BYTES:
                        skipped += 1
                        if len(skipped_paths) < _MAX_LISTED_PATHS:
                            skipped_paths.append(_rel_for_display(root, resolved))
                        continue
                except OSError:
                    skipped += 1
                    continue
                files.append(resolved)
    files.sort()
    return files, skipped_paths, skipped


def _rel_for_display(root: Path, path: Path) -> str:
    """Vault-relative path for diagnostics; falls back to the name when the
    path is not syntactically under root (symlink escape targets)."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _decode_markdown(raw: bytes) -> str:
    """FIX-338：UTF-8 解码 + BOM 剥离一次（frontmatter 才能正常解析）。"""
    text = raw.decode("utf-8", errors="replace")
    if text.startswith("\ufeff"):
        text = text[1:]
    return text


def _normalize_body(text: str) -> str:
    """FIX-338：CRLF/CR → LF；保留有意义换行（绝不逐行 trim、绝不把
    代码块压平成一行）；仅去掉首尾空白行。"""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _frontmatter_tags(meta_tags: Any) -> list[str]:
    """FIX-333：tags 异常标量类型（int/date/bool…）降级为无 frontmatter
    标签——单个文件的类型怪癖绝不拖垮整个扫描批次。"""
    if isinstance(meta_tags, str):
        return [meta_tags]
    if isinstance(meta_tags, (list, tuple, set)):
        return [t for t in meta_tags if t]
    return []


def _frontmatter_properties(post: Any) -> dict[str, str]:
    """NEW-327：frontmatter 顶层标量字段 → 有界属性投影（键/值字符串化）。

    只读投影：值非标量（嵌套 dict 等）如实跳过；``tags`` 不进属性（有
    自己的域）。绝不回写文件——原 frontmatter 格式保持不变。"""
    metadata = getattr(post, "metadata", None)
    if not isinstance(metadata, dict):
        return {}
    props: dict[str, str] = {}
    for key, value in metadata.items():
        if not isinstance(key, str) or key == "tags":
            continue
        clean_key = key.strip()[:_MAX_PROPERTY_KEY]
        if not clean_key:
            continue
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif isinstance(value, (int, float)):
            text = str(value)
        elif isinstance(value, str):
            text = value.strip()
        elif isinstance(value, (list, tuple)):
            text = ", ".join(str(item) for item in value if item)
        else:
            continue  # 嵌套结构等非标量：诚实跳过，不臆造字符串
        if text:
            props[clean_key] = text[:_MAX_PROPERTY_VALUE]
        if len(props) >= _MAX_PROPERTIES:
            break
    return props


def parse_note(resolved_path: Path, root: Path) -> dict[str, Any] | None:
    """One file → projection payload (frontmatter + wikilinks + text).

    FIX-333：整个单文件解析是 total 的——任何异常都降级为 None（该文件
    进 skipped 诊断，批次照常），绝不冒泡拖垮整批。
    """
    try:
        rel_path = resolved_path.relative_to(root).as_posix()
        try:
            stat = resolved_path.stat()
        except OSError:
            return None
        try:
            raw = resolved_path.read_bytes()
        except OSError:
            return None
        if b"\x00" in raw[:4096]:
            return None  # binary masquerading as .md
        fingerprint = f"{stat.st_mtime_ns}:{stat.st_size}"
        content_hash = hashlib.sha256(raw).hexdigest()
        try:
            post = fm_module.loads(_decode_markdown(raw))
        except Exception:
            return None
        tags = [
            str(t).lstrip("#")[:_MAX_TAG_LENGTH]
            for t in _frontmatter_tags(post.get("tags", []))
        ]
        body = _normalize_body(str(post.content or ""))
        wikilinks: list[str] = []
        wikilink_raws: list[str] = []
        for chunk in body.split("[[")[1:]:
            target = chunk.split("]]", 1)[0]
            raw = target.strip()
            target = target.split("|", 1)[0].split("#", 1)[0].strip()
            if raw and raw not in wikilink_raws:
                wikilink_raws.append(raw[:200])  # F080：保留别名/锚点原文
            if target and target not in wikilinks:
                wikilinks.append(target[:200])
        inline_tags: list[str] = []
        for token in body.replace("]", " ").split():
            if token.startswith("#") and len(token) > 1:
                candidate = token.lstrip("#")[:_MAX_TAG_LENGTH]
                if candidate.isprintable() and candidate not in inline_tags:
                    inline_tags.append(candidate)
        for candidate in inline_tags:
            if candidate not in tags:
                tags.append(candidate)
        text = body
        title = str(post.get("title") or resolved_path.stem)
        truncated = (
            len(text) > _MAX_BODY_LENGTH
            or len(tags) > 30
            or len(wikilinks) > _MAX_WIKILINKS
            or len(title) > _MAX_TITLE_LENGTH
        )
        return {
            "rel_path": rel_path,
            "fingerprint": fingerprint,
            "content_hash": content_hash,
            "title": title[:_MAX_TITLE_LENGTH],
            "tags": tags[:30],
            "wikilinks": wikilinks[:_MAX_WIKILINKS],
            "wikilink_raws": wikilink_raws[:_MAX_WIKILINKS],
            "body_text": text[:_MAX_BODY_LENGTH],
            "properties": _frontmatter_properties(post),
            "truncated": 1 if truncated else 0,
        }
    except Exception:  # noqa: BLE001 — FIX-333：单文件异常 = 单文件降级
        _logger.debug("parse_note degraded per-file", exc_info=True)
        return None


@dataclass(frozen=True)
class ScanPlan:
    """NEW-323：一次扫描的差异计划（walk + parse + 与投影对比的结果）。

    计划阶段零写入——``rescan()`` 是唯一的应用者，同步审批预览直接消费
    同一个计划，保证「预览看到的差异」与「确认后应用的差异」同一口径。"""

    root: Path
    new_uuids: list[tuple[str, dict[str, Any]]]
    updates: list[tuple[str, dict[str, Any], str]]  # (uuid, note, kind)
    removed_uuids: list[str]
    removed_paths: list[str]
    added: int
    changed: int
    removed: int
    renames: int
    unchanged: int
    truncated_notes: int
    skipped: int
    scan_files: dict[str, Any]

    def counts(self) -> dict[str, int]:
        return {
            "added": self.added,
            "changed": self.changed,
            "removed": self.removed,
            "renames": self.renames,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
            "truncatedNotes": self.truncated_notes,
        }


class ObsidianService:
    """Scan orchestration + projection maintenance (read-only)."""

    def __init__(self, db: Database, env_root: str = "") -> None:
        self._db = db
        self._env_root = (env_root or "").strip()

    async def get_vault_path(self) -> str:
        """The EFFECTIVE vault root (env wins over the DB setting)."""
        if self._env_root:
            return self._env_root
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT vault_path FROM obsidian_settings WHERE id = 1"
        )
        return str(row["vault_path"]) if row is not None else ""

    async def set_vault_path(self, vault_path: str) -> Path:
        if self._env_root:
            raise VaultRootLocked(
                "Vault 根目录由部署环境固定（LUMIRSS_OBSIDIAN_VAULT_DIR），"
                "无法通过 API 修改。"
            )
        canonical = canonical_vault_root(vault_path)
        await self._db.migrate()
        await self._db.execute(
            "UPDATE obsidian_settings SET vault_path = ?, last_error = NULL WHERE id = 1",
            (str(canonical),),
        )
        return canonical

    async def env_root_configured(self) -> bool:
        return bool(self._env_root)

    async def get_status(self) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT vault_path, last_scan_at, last_error, last_scan_files_json FROM obsidian_settings WHERE id = 1"
        )
        count_row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM obsidian_notes"
        )
        return {
            "vaultPath": str(row["vault_path"]) if row is not None else "",
            "lastScanAt": row["last_scan_at"] if row is not None else None,
            "lastError": row["last_error"] if row is not None else None,
            "noteCount": int(count_row["n"]) if count_row is not None else 0,
            "envRootConfigured": bool(self._env_root),
            # N138：最近一次扫描的文件级诊断（从未扫描 / 字段缺失 → None，
            # UI 保持既有的诚实空态，绝不冒充「已自动同步」）。
            "lastScanFiles": _load_scan_files_json(
                row["last_scan_files_json"] if row is not None else ""
            ),
        }

    async def note_count(self) -> int:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM obsidian_notes"
        )
        return int(row["n"]) if row is not None else 0

    async def scan_if_configured(self) -> dict[str, Any] | None:
        """One incremental scan when a vault root is usable; else None.

        Used by the background poll loop — an unconfigured vault is a
        no-op, never an error storm.
        """
        vault_path = await self.get_vault_path()
        if not vault_path:
            return None
        try:
            return await self.rescan()
        except (VaultUnreachable, VaultPermissionDenied):
            # Recorded on the settings row by rescan(); the loop keeps
            # polling so a late mount self-heals.
            return None

    async def _plan(self) -> ScanPlan:
        """Diff computation shared by rescan() and the NEW-323 sync
        approval preview: walk + parse + compare against the projection.
        Strictly read-only — the apply phase below is the only writer, so
        a preview can never mutate the mirror."""
        vault_path = await self.get_vault_path()
        root = canonical_vault_root(vault_path)
        loop_files, skipped_paths, skipped = await _to_thread(
            _iter_markdown_files, root
        )
        known = {
            str(row["rel_path"]): {
                "fingerprint": str(row["fingerprint"]),
                "content_hash": str(row["content_hash"]),
                "item_uuid": str(row["item_uuid"]),
            }
            for row in await self._db.fetch_all(
                "SELECT rel_path, fingerprint, content_hash, item_uuid FROM obsidian_notes"
            )
        }
        # Parse everything on the worker thread first; the mutation phase
        # below is one atomic batch.
        parsed: dict[str, dict[str, Any]] = {}
        seen_paths: set[str] = set()
        for resolved in loop_files:
            note = parse_note(resolved, root)
            if note is None:
                skipped += 1
                if len(skipped_paths) < _MAX_LISTED_PATHS:
                    skipped_paths.append(_rel_for_display(root, resolved))
                continue
            seen_paths.add(note["rel_path"])
            parsed[note["rel_path"]] = note
        removed_paths = set(known) - seen_paths
        # Donor pool: removed paths by content hash. A rename is adopted
        # only when ONE removed path and ONE new path share a hash —
        # several candidates on either side make ownership ambiguous.
        donors_by_hash: dict[str, list[str]] = {}
        for rel in removed_paths:
            donors_by_hash.setdefault(known[rel]["content_hash"], []).append(rel)
        claimants_by_hash: dict[str, int] = {}
        for rel, note in parsed.items():
            if rel not in known:
                claimants_by_hash[note["content_hash"]] = (
                    claimants_by_hash.get(note["content_hash"], 0) + 1
                )

        def _donor_for(note: dict[str, Any]) -> str | None:
            if claimants_by_hash.get(note["content_hash"], 0) != 1:
                return None
            candidates = donors_by_hash.get(note["content_hash"], [])
            return candidates[0] if len(candidates) == 1 else None

        added = changed = removed = renames = unchanged = 0
        truncated_notes = 0
        new_uuids: list[tuple[str, dict[str, Any]]] = []
        updates: list[tuple[str, dict[str, Any], str]] = []  # (uuid, note, kind)
        # N138：文件级诊断（新增/更改的 rel_path；删除与跳过在下方汇总）。
        added_paths: list[str] = []
        changed_paths: list[str] = []
        for rel, note in parsed.items():
            existing = known.get(rel)
            if existing is None:
                donor_rel = _donor_for(note)
                if donor_rel is not None:
                    removed_paths.discard(donor_rel)
                    updates.append((known[donor_rel]["item_uuid"], note, "rename"))
                    renames += 1
                else:
                    new_uuids.append((new_library_uuid(), note))
                    added += 1
                    added_paths.append(rel)
                truncated_notes += int(note["truncated"])
                continue
            if existing["fingerprint"] == note["fingerprint"]:
                unchanged += 1
                truncated_notes += int(note["truncated"])
                continue
            updates.append((existing["item_uuid"], note, "change"))
            changed += 1
            changed_paths.append(rel)
            truncated_notes += int(note["truncated"])
        removed_uuids = [known[rel]["item_uuid"] for rel in removed_paths]
        removed += len(removed_uuids)
        scan_files = build_scan_files_report(
            added=added_paths,
            changed=changed_paths,
            removed=sorted(removed_paths),
            skipped=skipped_paths,
        )
        return ScanPlan(
            root=root,
            new_uuids=new_uuids,
            updates=updates,
            removed_uuids=removed_uuids,
            removed_paths=sorted(removed_paths),
            added=added,
            changed=changed,
            removed=removed,
            renames=renames,
            unchanged=unchanged,
            truncated_notes=truncated_notes,
            skipped=skipped,
            scan_files=scan_files,
        )

    async def sync_preview(self) -> dict[str, Any]:
        """NEW-323 同步审批预览：与 rescan 同一差异计划，但【零写入】——
        镜像（obsidian_notes 投影）在用户确认之前绝不更新。新增/修改/
        删除清单来自真实 walk + parse，不是上次的缓存报告。"""
        started = utc_now()
        plan = await self._plan()
        result: dict[str, Any] = plan.counts()
        result["elapsedMs"] = _elapsed_ms(started)
        result["vaultPath"] = str(plan.root)
        result["files"] = plan.scan_files
        return result

    async def rescan(self) -> dict[str, Any]:
        """Full scan: incremental fingerprint short-circuit; renames
        adopted only when unambiguous; one transaction per batch.

        NEW-323：拆成 _plan()（零写入差异计算）+ 本方法的应用阶段——
        应用是唯一写镜像的路径，审批预览复用同一计划口径。"""
        from lumirss.db_tx import transaction

        started = utc_now()
        try:
            plan = await self._plan()
        except (VaultUnreachable, VaultPermissionDenied) as exc:
            await self._db.migrate()
            await self._db.execute(
                "UPDATE obsidian_settings SET last_error = ? WHERE id = 1",
                (str(exc)[:500],),
            )
            raise
        plan_scan_files = plan.scan_files

        def apply(connection) -> None:  # noqa: ANN001 — raw sqlite3 connection
            now = utc_now()
            for item_uuid, note in plan.new_uuids:
                connection.execute(
                    "INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'obsidian_note', ?)",
                    (item_uuid, now),
                )
                connection.execute(
                    "INSERT INTO obsidian_notes (item_uuid, rel_path, fingerprint, content_hash, title, tags, wikilinks, wikilink_raws, body_text, truncated, properties_json, indexed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item_uuid,
                        note["rel_path"],
                        note["fingerprint"],
                        note["content_hash"],
                        note["title"],
                        json.dumps(note["tags"], ensure_ascii=False),
                        json.dumps(note["wikilinks"], ensure_ascii=False),
                        json.dumps(note["wikilink_raws"], ensure_ascii=False),
                        note["body_text"],
                        note["truncated"],
                        json.dumps(note["properties"], ensure_ascii=False),
                        now,
                    ),
                )
                _search_upsert(
                    connection,
                    ref=f"library:{item_uuid}",
                    kind="obsidian_note",
                    title=note["title"],
                    body=note["body_text"][:4000],
                )
            for item_uuid, note, _kind in plan.updates:
                connection.execute(
                    "UPDATE obsidian_notes SET rel_path = ?, fingerprint = ?, content_hash = ?, title = ?, tags = ?, wikilinks = ?, wikilink_raws = ?, body_text = ?, truncated = ?, properties_json = ?, indexed_at = ? WHERE item_uuid = ?",
                    (
                        note["rel_path"],
                        note["fingerprint"],
                        note["content_hash"],
                        note["title"],
                        json.dumps(note["tags"], ensure_ascii=False),
                        json.dumps(note["wikilinks"], ensure_ascii=False),
                        json.dumps(note["wikilink_raws"], ensure_ascii=False),
                        note["body_text"],
                        note["truncated"],
                        json.dumps(note["properties"], ensure_ascii=False),
                        now,
                        item_uuid,
                    ),
                )
                _search_upsert(
                    connection,
                    ref=f"library:{item_uuid}",
                    kind="obsidian_note",
                    title=note["title"],
                    body=note["body_text"][:4000],
                )
            for item_uuid in plan.removed_uuids:
                connection.execute(
                    "DELETE FROM library_items WHERE uuid = ?", (item_uuid,)
                )
                connection.execute(
                    "DELETE FROM search_library WHERE ref = ?", (f"library:{item_uuid}",)
                )
            connection.execute(
                "UPDATE obsidian_settings SET last_scan_at = ?, last_error = NULL, last_scan_files_json = ? WHERE id = 1",
                (utc_now(), json.dumps(plan_scan_files, ensure_ascii=False)),
            )

        await transaction(self._db, apply)
        elapsed_ms = _elapsed_ms(started)
        report = ScanReport(
            added=plan.added,
            changed=plan.changed,
            removed=plan.removed,
            renames=plan.renames,
            unchanged=plan.unchanged,
            skipped=plan.skipped,
            truncated_notes=plan.truncated_notes,
            elapsed_ms=elapsed_ms,
        )
        result = report.to_dict()
        result["vaultPath"] = str(plan.root)
        # N138：文件级诊断（本批列表随报告返回 + 已持久化为「最近一次」）。
        result["files"] = plan_scan_files
        # F080：重建反向链接索引（尽力而为；失败不影响 rescan 结果）
        import contextlib as _contextlib

        from lumirss.obsidian_backlinks import rebuild_backlinks, rebuild_block_refs

        with _contextlib.suppress(Exception):
            result["backlinksRebuilt"] = await rebuild_backlinks(self._db) >= 0
        # N134：块 id 索引同样尽力而为（失败不影响扫描结果）。
        with _contextlib.suppress(Exception):
            await rebuild_block_refs(self._db)
        return result

    async def list_notes(
        self, *, q: str | None = None, limit: int = 50, cursor: str | None = None
    ) -> list[dict[str, Any]]:
        await self._db.migrate()
        like = (
            f"%{_escape_like(q.strip())}%" if q and q.strip() else None
        )
        rows = await self._db.fetch_all(
            "SELECT item_uuid, rel_path, title, tags, wikilinks, indexed_at FROM obsidian_notes WHERE (? IS NULL OR title LIKE ? ESCAPE '\\' OR body_text LIKE ? ESCAPE '\\') ORDER BY rel_path ASC LIMIT ?",
            (like, like, like, max(1, min(limit, 200))),
        )
        return [
            {
                "ref": f"library:{row['item_uuid']}",
                "relPath": str(row["rel_path"]),
                "title": str(row["title"]),
                "tags": json.loads(str(row["tags"])),
                "wikilinks": json.loads(str(row["wikilinks"])),
                "indexedAt": str(row["indexed_at"]),
            }
            for row in rows
        ]

    async def get_note(self, item_uuid: str) -> dict[str, Any] | None:
        """The indexed snapshot of one note, rendered consistently.

        Body, tags, wikilinks and html all come from the same indexed row
        (P0-09f); the live file may be ahead until the next scan. No
        vault access happens here, so a temporarily unmounted vault
        cannot make indexed content unreadable.
        """
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT item_uuid, rel_path, title, tags, wikilinks, body_text, truncated, properties_json, indexed_at FROM obsidian_notes WHERE item_uuid = ?",
            (item_uuid,),
        )
        if row is None:
            return None
        import mistune

        body_text = str(row["body_text"] or "")
        # mistune is pure-Python CPU: a large note rendered inline would
        # stall the event loop for every concurrent request.
        html = await _to_thread(mistune.html, body_text) if body_text else ""
        try:
            properties = json.loads(str(row["properties_json"] or "{}"))
        except json.JSONDecodeError:
            properties = {}
        return {
            "ref": f"library:{row['item_uuid']}",
            "relPath": str(row["rel_path"]),
            "title": str(row["title"]),
            "tags": json.loads(str(row["tags"])),
            "wikilinks": json.loads(str(row["wikilinks"])),
            "bodyText": body_text,
            "contentHtml": html,
            "truncated": bool(row["truncated"]),
            "properties": properties if isinstance(properties, dict) else {},
            "indexedAt": str(row["indexed_at"]),
        }


def _search_upsert(
    connection, *, ref: str, kind: str, title: str, body: str
) -> None:  # noqa: ANN001 — raw sqlite3 connection
    """search_library projection write on the SCAN'S connection (the
    LibrarySearchWriter commits per statement — wrong inside a batch)."""
    existing = connection.execute(
        "SELECT ref FROM search_library WHERE ref = ?", (ref,)
    ).fetchone()
    now = utc_now()
    if existing is None:
        connection.execute(
            "INSERT INTO search_library (ref, kind, title, body, url, updated_at) VALUES (?, ?, ?, ?, NULL, ?)",
            (ref, kind, title, body, now),
        )
    else:
        connection.execute(
            "UPDATE search_library SET kind = ?, title = ?, body = ?, url = NULL, updated_at = ? WHERE ref = ?",
            (kind, title, body, now, ref),
        )


async def _to_thread(func, *args):
    import asyncio

    return await asyncio.to_thread(func, *args)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _load_scan_files_json(raw: Any) -> dict[str, Any] | None:
    """N138：持久化的最近一次扫描文件级诊断；缺失/损坏 → None（诚实）。"""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def check_vault_path(vault_path: str, rel: str) -> bool | None:
    """N139 附件存在性核对（只读）：True 存在 / False 缺失 / None 无法核对。

    Vault 不可达或路径越出根（containment 拒绝）都返回 None —— 校验报告
    只在确有把握时才报 missing_attachment，绝不凭空报假阳性。"""
    try:
        root = canonical_vault_root(vault_path)
    except (VaultUnreachable, VaultPermissionDenied):
        return None
    candidate = root / str(rel or "").strip()
    resolved = _contained(root, candidate)
    if resolved is None:
        return None
    try:
        return resolved.is_file()
    except OSError:
        return None


def _elapsed_ms(started_iso: str) -> int:
    from datetime import datetime

    started = datetime.fromisoformat(started_iso)
    delta = datetime.fromisoformat(utc_now()) - started
    return int(delta.total_seconds() * 1000)
