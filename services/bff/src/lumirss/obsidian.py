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
        "body_text": text[:_MAX_BODY_LENGTH],
        "truncated": 1 if truncated else 0,
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
            "envRootConfigured": bool(self._env_root),
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

    async def rescan(self) -> dict[str, Any]:
        """Full scan: incremental fingerprint short-circuit; renames
        adopted only when unambiguous; one transaction per batch."""
        from lumirss.db_tx import transaction

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
        # Parse everything on the worker thread first; the mutation phase
        # below is one atomic batch.
        parsed: dict[str, dict[str, Any]] = {}
        seen_paths: set[str] = set()
        for resolved in loop_files:
            note = parse_note(resolved, root)
            if note is None:
                skipped += 1
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
                truncated_notes += int(note["truncated"])
                continue
            if existing["fingerprint"] == note["fingerprint"]:
                unchanged += 1
                truncated_notes += int(note["truncated"])
                continue
            updates.append((existing["item_uuid"], note, "change"))
            changed += 1
            truncated_notes += int(note["truncated"])
        removed_uuids = [known[rel]["item_uuid"] for rel in removed_paths]
        removed += len(removed_uuids)

        def apply(connection) -> None:  # noqa: ANN001 — raw sqlite3 connection
            now = utc_now()
            for item_uuid, note in new_uuids:
                connection.execute(
                    "INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'obsidian_note', ?)",
                    (item_uuid, now),
                )
                connection.execute(
                    "INSERT INTO obsidian_notes (item_uuid, rel_path, fingerprint, content_hash, title, tags, wikilinks, body_text, truncated, indexed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item_uuid,
                        note["rel_path"],
                        note["fingerprint"],
                        note["content_hash"],
                        note["title"],
                        json.dumps(note["tags"], ensure_ascii=False),
                        json.dumps(note["wikilinks"], ensure_ascii=False),
                        note["body_text"],
                        note["truncated"],
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
            for item_uuid, note, _kind in updates:
                connection.execute(
                    "UPDATE obsidian_notes SET rel_path = ?, fingerprint = ?, content_hash = ?, title = ?, tags = ?, wikilinks = ?, body_text = ?, truncated = ?, indexed_at = ? WHERE item_uuid = ?",
                    (
                        note["rel_path"],
                        note["fingerprint"],
                        note["content_hash"],
                        note["title"],
                        json.dumps(note["tags"], ensure_ascii=False),
                        json.dumps(note["wikilinks"], ensure_ascii=False),
                        note["body_text"],
                        note["truncated"],
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
            for item_uuid in removed_uuids:
                connection.execute(
                    "DELETE FROM library_items WHERE uuid = ?", (item_uuid,)
                )
                connection.execute(
                    "DELETE FROM search_library WHERE ref = ?", (f"library:{item_uuid}",)
                )
            connection.execute(
                "UPDATE obsidian_settings SET last_scan_at = ?, last_error = NULL WHERE id = 1",
                (utc_now(),),
            )

        await transaction(self._db, apply)
        elapsed_ms = _elapsed_ms(started)
        report = ScanReport(
            added=added,
            changed=changed,
            removed=removed,
            renames=renames,
            unchanged=unchanged,
            skipped=skipped,
            truncated_notes=truncated_notes,
            elapsed_ms=elapsed_ms,
        )
        result = report.to_dict()
        result["vaultPath"] = str(root)
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
            "SELECT item_uuid, rel_path, title, tags, wikilinks, body_text, truncated, indexed_at FROM obsidian_notes WHERE item_uuid = ?",
            (item_uuid,),
        )
        if row is None:
            return None
        import mistune

        body_text = str(row["body_text"] or "")
        html = mistune.html(body_text) if body_text else ""
        return {
            "ref": f"library:{row['item_uuid']}",
            "relPath": str(row["rel_path"]),
            "title": str(row["title"]),
            "tags": json.loads(str(row["tags"])),
            "wikilinks": json.loads(str(row["wikilinks"])),
            "bodyText": body_text,
            "contentHtml": html,
            "truncated": bool(row["truncated"]),
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


def _elapsed_ms(started_iso: str) -> int:
    from datetime import datetime

    started = datetime.fromisoformat(started_iso)
    delta = datetime.fromisoformat(utc_now()) - started
    return int(delta.total_seconds() * 1000)
