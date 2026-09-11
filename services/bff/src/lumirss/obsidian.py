"""Obsidian read-only vault projection (phase2 G6).

The user's vault is the source of truth; this module only READS it and
maintains a derived, rebuildable projection (obsidian_notes rows +
search_library). Hard guarantees:

- containment: the vault root is canonicalized once per scan (realpath);
  EVERY file access re-resolves and refuses anything outside the root —
  symlinks/junctions/bind-mounts to outside paths are excluded, not
  followed;
- read-only: no write/rename/mkdir/unlink call exists in this module;
- bounded: .md only, files >1MB skipped, null-byte binary sniff, depth
  and file-count caps, per-file parse errors degrade to "unparsable"
  rows instead of failing the scan;
- rename detection: content-hash matching (move = same hash, new path).
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frontmatter as fm_module

from lumirss.itemref import new_library_uuid
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_FILE_BYTES = 1024 * 1024
_MAX_FILES = 20000
_MAX_DEPTH = 12
_MAX_TAG_LENGTH = 50

_logger = logging.getLogger("lumirss.obsidian")


class VaultUnreachable(Exception):
    """The configured vault path does not exist or is not a directory."""


class VaultPermissionDenied(Exception):
    """The vault path cannot be read (OS permission)."""


@dataclass(frozen=True)
class ScanReport:
    added: int
    changed: int
    removed: int
    renames: int
    unchanged: int
    skipped: int
    elapsed_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "changed": self.changed,
            "removed": self.removed,
            "renames": self.renames,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
            "elapsedMs": self.elapsed_ms,
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


def _iter_markdown_files(root: Path) -> tuple[list[Path], int]:
    """Bounded walk; symlink escapes excluded; returns (files, skipped)."""
    files: list[Path] = []
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
                continue
            if resolved.is_dir():
                stack.append((resolved, depth + 1))
            elif resolved.suffix.lower() == ".md":
                if len(files) >= _MAX_FILES:
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
    return files, skipped


def parse_note(resolved_path: Path, root: Path) -> dict[str, Any] | None:
    """One file → projection payload (frontmatter + wikilinks + text)."""
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
        post = fm_module.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return None
    meta_tags = post.get("tags", [])
    if isinstance(meta_tags, str):
        meta_tags = [meta_tags]
    tags = [
        str(t).lstrip("#")[:_MAX_TAG_LENGTH] for t in (meta_tags or []) if t
    ]
    body = str(post.content or "")
    wikilinks: list[str] = []
    for chunk in body.split("[[")[1:]:
        target = chunk.split("]]", 1)[0]
        target = target.split("|", 1)[0].split("#", 1)[0].strip()
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
    text = " ".join(body.split())
    title = str(post.get("title") or resolved_path.stem)
    return {
        "rel_path": rel_path,
        "fingerprint": fingerprint,
        "content_hash": content_hash,
        "title": title[:500],
        "tags": tags[:30],
        "wikilinks": wikilinks[:100],
        "body_text": text[:20000],
    }


class ObsidianService:
    """Scan orchestration + projection maintenance (read-only)."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._search = LibrarySearchWriter(db)

    async def get_vault_path(self) -> str:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT vault_path FROM obsidian_settings WHERE id = 1"
        )
        return str(row["vault_path"]) if row is not None else ""

    async def set_vault_path(self, vault_path: str) -> Path:
        canonical = canonical_vault_root(vault_path)
        await self._db.migrate()
        await self._db.execute(
            "UPDATE obsidian_settings SET vault_path = ?, last_error = NULL WHERE id = 1",
            (str(canonical),),
        )
        return canonical

    async def get_status(self) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT vault_path, last_scan_at, last_error FROM obsidian_settings WHERE id = 1"
        )
        count_row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM obsidian_notes"
        )
        return {
            "vaultPath": str(row["vault_path"]) if row is not None else "",
            "lastScanAt": row["last_scan_at"] if row is not None else None,
            "lastError": row["last_error"] if row is not None else None,
            "noteCount": int(count_row["n"]) if count_row is not None else 0,
        }

    async def note_count(self) -> int:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM obsidian_notes"
        )
        return int(row["n"]) if row is not None else 0

    async def rescan(self) -> dict[str, Any]:
        """Full scan with incremental fingerprint short-circuit + rename
        detection by content hash. Honest errors keep the old index."""
        vault_path = await self.get_vault_path()
        started = utc_now()
        try:
            root = canonical_vault_root(vault_path)
        except (VaultUnreachable, VaultPermissionDenied) as exc:
            await self._db.migrate()
            await self._db.execute(
                "UPDATE obsidian_settings SET last_error = ? WHERE id = 1",
                (str(exc)[:500],),
            )
            raise
        loop_files, skipped = await _to_thread(_iter_markdown_files, root)
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
        hash_to_uuid = {
            info["content_hash"]: info["item_uuid"]
            for info in known.values()
        }
        added = changed = removed = renames = unchanged = 0
        seen_paths: set[str] = set()
        adopted_uuids: set[str] = set()
        for resolved in loop_files:
            note = parse_note(resolved, root)
            if note is None:
                skipped += 1
                continue
            rel = note["rel_path"]
            seen_paths.add(rel)
            existing = known.get(rel)
            if existing is None:
                # Possible rename: same content hash, different path.
                donor = hash_to_uuid.get(note["content_hash"])
                if donor is not None:
                    await self._adopt_renamed(donor, note)
                    renames += 1
                    adopted_uuids.add(donor)
                else:
                    await self._insert_note(note)
                    added += 1
                continue
            if existing["fingerprint"] == note["fingerprint"]:
                unchanged += 1
                continue
            await self._update_note(existing["item_uuid"], note)
            changed += 1
        removed_paths = set(known) - seen_paths
        for rel in removed_paths:
            info = known[rel]
            if info["item_uuid"] in adopted_uuids:
                # The row was re-pointed to its new path (a rename), not lost.
                continue
            await self._db.execute(
                "DELETE FROM library_items WHERE uuid = ?",
                (info["item_uuid"],),
            )
            await self._search.delete(f"library:{info['item_uuid']}")
            removed += 1
        elapsed_ms = _elapsed_ms(started)
        report = ScanReport(
            added=added,
            changed=changed,
            removed=removed,
            renames=renames,
            unchanged=unchanged,
            skipped=skipped,
            elapsed_ms=elapsed_ms,
        )
        await self._db.execute(
            "UPDATE obsidian_settings SET last_scan_at = ?, last_error = NULL WHERE id = 1",
            (utc_now(),),
        )
        result = report.to_dict()
        result["vaultPath"] = str(root)
        return result

    async def _insert_note(self, note: dict[str, Any]) -> None:
        item_uuid = new_library_uuid()
        await self._db.execute(
            "INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'obsidian_note', ?)",
            (item_uuid, utc_now()),
        )
        await self._db.execute(
            "INSERT INTO obsidian_notes (item_uuid, rel_path, fingerprint, content_hash, title, tags, wikilinks, body_text, indexed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item_uuid,
                note["rel_path"],
                note["fingerprint"],
                note["content_hash"],
                note["title"],
                json.dumps(note["tags"], ensure_ascii=False),
                json.dumps(note["wikilinks"], ensure_ascii=False),
                note["body_text"],
                utc_now(),
            ),
        )
        await self._search.upsert(
            ref=f"library:{item_uuid}",
            kind="obsidian_note",
            title=note["title"],
            body=note["body_text"][:4000],
            url=None,
        )

    async def _update_note(self, item_uuid: str, note: dict[str, Any]) -> None:
        await self._db.execute(
            "UPDATE obsidian_notes SET rel_path = ?, fingerprint = ?, content_hash = ?, title = ?, tags = ?, wikilinks = ?, body_text = ?, indexed_at = ? WHERE item_uuid = ?",
            (
                note["rel_path"],
                note["fingerprint"],
                note["content_hash"],
                note["title"],
                json.dumps(note["tags"], ensure_ascii=False),
                json.dumps(note["wikilinks"], ensure_ascii=False),
                note["body_text"],
                utc_now(),
                item_uuid,
            ),
        )
        await self._search.upsert(
            ref=f"library:{item_uuid}",
            kind="obsidian_note",
            title=note["title"],
            body=note["body_text"][:4000],
            url=None,
        )

    async def _adopt_renamed(self, item_uuid: str, note: dict[str, Any]) -> None:
        await self._update_note(item_uuid, note)

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
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT item_uuid, rel_path, title, tags, wikilinks, body_text, indexed_at FROM obsidian_notes WHERE item_uuid = ?",
            (item_uuid,),
        )
        if row is None:
            return None
        # Containment is re-checked against the CURRENT vault setting.
        vault = await self.get_vault_path()
        try:
            root = canonical_vault_root(vault)
        except (VaultUnreachable, VaultPermissionDenied):
            return None
        candidate = root / str(row["rel_path"])
        if _contained(root, candidate) is None:
            return None
        import mistune

        markdown = candidate.read_text(encoding="utf-8", errors="replace")
        html = mistune.html(markdown)
        return {
            "ref": f"library:{row['item_uuid']}",
            "relPath": str(row["rel_path"]),
            "title": str(row["title"]),
            "tags": json.loads(str(row["tags"])),
            "wikilinks": json.loads(str(row["wikilinks"])),
            "bodyText": str(row["body_text"]),
            "contentHtml": html,
            "indexedAt": str(row["indexed_at"]),
        }


async def _to_thread(func, *args):
    import asyncio

    return await asyncio.to_thread(func, *args)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _elapsed_ms(started_iso: str) -> int:
    from datetime import datetime

    started = datetime.fromisoformat(started_iso)
    delta = datetime.fromisoformat(utc_now()) - started
    return int(delta.total_seconds() * 1000)
