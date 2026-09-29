"""NEW-326 附件引用可移植打包 —— 选中笔记 + 允许包含的附件 → 相对
链接目录（zip），并校验包内没有越界引用。

口径（绝不写 Vault）：

- 输入：用户选中的投影笔记（obsidian_notes uuid，≤100）；
- 附件收集：笔记内容里的 ``![[path]]`` 嵌入与 ``![alt](src)`` 相对
  图片链接；扩展名在允许清单内、经 containment 校验确在 Vault 内、
  存在且 ≤1MB、总量 ≤20MB 才收录；
- 重写：收录附件的引用改写为包内相对链接 ``../attachments/<名>``；
  未收录（越界 / 缺失 / 扩展名不允许 / 超预算）的引用以 HTML 注释
  如实标记并从内容中移除——包内绝不残留指向包外的文件引用；
- 终检：重写后再扫一遍全部链接目标，凡 ``..``、绝对路径、file: 即
  violation（双保险，结果随台账如实落库）；
- zip 即时组装返回（notes/ + attachments/ + manifest.json），不落
  二进制；下载端点按台账从当前 Vault 重装（内容可能已更新，如实说明）。

per-user：打包面是 owner 的 Vault（路由层 owner 门槛），A 打的包
对 B 不可见。
"""

import io
import json
import posixpath
import re
import uuid as _uuid
import zipfile
from pathlib import Path
from typing import Any

from lumirss.obsidian import _contained, canonical_vault_root
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_BUNDLE_NOTES = 100
MAX_ATTACHMENT_BYTES = 1024 * 1024
MAX_BUNDLE_TOTAL_BYTES = 20 * 1024 * 1024

ALLOWED_ATTACHMENT_EXTS = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif", ".bmp",
        ".pdf", ".mp3", ".m4a", ".wav", ".ogg", ".mp4", ".webm", ".zip",
    }
)

_EMBED_RE = re.compile(r"!\[\[([^\]]+)\]\]")
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_SAFE_NAME_RE = re.compile(r"[/\\:*?\"<>|]")


class BundleInvalid(ValueError):
    """打包请求非法（映射 400）。"""


def _safe_name(name: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("-", str(name or "").strip()).strip("- .")
    return cleaned or "附件"


def _unique_name(name: str, used: set[str]) -> str:
    if name not in used:
        used.add(name)
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    counter = 2
    while True:
        candidate = f"{stem}-{counter}{ext}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        counter += 1


def _embed_target(raw: str) -> str:
    return raw.split("|", 1)[0].split("#", 1)[0].strip()


def _is_remote(src: str) -> bool:
    return "://" in src or src.startswith("data:") or src.startswith("obsidian://")


class PortableBundleBuilder:
    def __init__(self, db: Database, vault_path: str) -> None:
        self._db = db
        self._vault_path = vault_path

    async def build(self, note_refs: list[str]) -> dict[str, Any]:
        """组装包 → {manifest, files: {arcname: bytes}}（零 Vault 写入）。"""
        await self._db.migrate()
        if not self._vault_path.strip():
            raise BundleInvalid("尚未配置 Vault，无法读取笔记与附件。")
        if not isinstance(note_refs, list):
            raise BundleInvalid("noteRefs 必须是字符串数组。")
        ordered: list[str] = []
        for ref in note_refs:
            clean = str(ref).strip().replace("library:", "")
            if clean and clean not in ordered:
                ordered.append(clean)
        if not ordered:
            raise BundleInvalid("noteRefs 不能为空。")
        if len(ordered) > MAX_BUNDLE_NOTES:
            raise BundleInvalid(f"一次最多打包 {MAX_BUNDLE_NOTES} 篇笔记。")
        root = canonical_vault_root(self._vault_path)
        rows = await self._db.fetch_all(
            "SELECT item_uuid, rel_path, title, body_text FROM obsidian_notes ORDER BY rel_path ASC LIMIT 5000"
        )
        by_uuid = {str(row["item_uuid"]): row for row in rows}
        unknown = [ref for ref in ordered if ref not in by_uuid]
        if unknown:
            raise BundleInvalid(f"以下笔记不在投影中：{', '.join(unknown[:5])}")

        notes_out: list[dict[str, Any]] = []
        attachments_out: list[dict[str, Any]] = []
        violations: list[dict[str, str]] = []
        files: dict[str, bytes] = {}
        used_attachment_names: set[str] = set()
        used_note_names: set[str] = set()
        total_bytes = 0

        for ref in ordered:
            row = by_uuid[ref]
            rel_path = str(row["rel_path"])
            source = _contained(root, root / rel_path)
            if source is None or not source.is_file():
                violations.append(
                    {
                        "kind": "source_missing",
                        "detail": f"笔记 {rel_path} 在 Vault 中不可读（越界或缺失），已跳过。",
                    }
                )
                continue
            raw = source.read_bytes()
            text = raw.decode("utf-8", errors="replace")
            # 附件引用按笔记所在目录解析（Obsidian 相对链接语义）
            note_dir = root / Path(rel_path).parent
            rewritten, note_attachments = self._collect_and_rewrite(
                text,
                root,
                note_dir,
                used_attachment_names,
                attachments_out,
                violations,
                files,
            )
            total_bytes = sum(len(data) for data in files.values()) + sum(
                item["bytes"] for item in attachments_out
            )
            if total_bytes > MAX_BUNDLE_TOTAL_BYTES:
                raise BundleInvalid("打包总量超过 20MiB 上限。")
            note_name = _unique_name(
                f"{_safe_name(Path(rel_path).stem)}.md", used_note_names
            )
            arcname = f"notes/{note_name}"
            files[arcname] = rewritten.encode("utf-8")
            notes_out.append(
                {
                    "noteUuid": ref,
                    "relPath": rel_path,
                    "title": str(row["title"] or ""),
                    "archivePath": arcname,
                    "attachments": note_attachments,
                }
            )
        leftover = self._final_boundary_check(files)
        violations.extend(leftover)
        manifest = {
            "id": "",  # 由调用方回填
            "notes": notes_out,
            "attachments": attachments_out,
            "violations": violations,
            "noteCount": len(notes_out),
            "attachmentCount": len(attachments_out),
            "violationCount": len(violations),
            "createdAt": utc_now(),
            "layout": {
                "notes/": "打包的笔记（附件引用已改写为 ../attachments/ 相对链接）",
                "attachments/": "允许包含的附件（Vault 内、白名单扩展名）",
            },
            "honestyNote": "打包只读 Vault：未收录（越界/缺失/不允许）的引用已如实移除并记入 violations。",
        }
        return {"manifest": manifest, "files": files}

    def _collect_and_rewrite(
        self,
        text: str,
        root: Path,
        note_dir: Path,
        used_names: set[str],
        attachments_out: list[dict[str, Any]],
        violations: list[dict[str, str]],
        files: dict[str, bytes],
    ) -> tuple[str, list[str]]:
        """收集 + 重写 + 校验单个笔记的附件引用。返回 (新文本, 附件名列表)。

        引用按笔记所在目录解析（Obsidian 相对链接语义）；containment
        仍以 Vault 根为界。"""
        included: list[str] = []

        def resolve_candidate(target: str) -> tuple[Path | None, str]:
            """(resolved, 拒绝原因)；resolved 为 None 时给出原因。"""
            clean = target.strip()
            if not clean or _is_remote(clean):
                return None, ""
            if ".." in clean or clean.startswith(("/", "\\")) or (
                len(clean) >= 2 and clean[1] == ":"
            ):
                return None, "escaped_vault"
            candidate = _contained(root, note_dir / clean)
            if candidate is None:
                return None, "escaped_vault"
            if candidate.suffix.lower() not in ALLOWED_ATTACHMENT_EXTS:
                return None, "extension_not_allowed"
            if not candidate.is_file():
                return None, "missing"
            try:
                if candidate.stat().st_size > MAX_ATTACHMENT_BYTES:
                    return None, "too_large"
            except OSError:
                return None, "missing"
            return candidate, ""

        def include(target: str) -> str | None:
            resolved, reason = resolve_candidate(target)
            if resolved is None:
                if reason:
                    violations.append(
                        {
                            "kind": reason,
                            "detail": f"附件引用 {target} 未打包（{'路径越出 Vault' if reason == 'escaped_vault' else '扩展名不允许' if reason == 'extension_not_allowed' else '文件缺失' if reason == 'missing' else '超过单文件上限'}）。",
                        }
                    )
                return None
            try:
                data = resolved.read_bytes()
            except OSError:
                violations.append(
                    {"kind": "missing", "detail": f"附件引用 {target} 读取失败，未打包。"}
                )
                return None
            name = _unique_name(_safe_name(resolved.name), used_names)
            arcname = f"attachments/{name}"
            existing = next(
                (item for item in attachments_out if item["archivePath"] == arcname),
                None,
            )
            if existing is None:
                attachments_out.append(
                    {
                        "sourcePath": resolved.relative_to(root).as_posix(),
                        "archivePath": arcname,
                        "bytes": len(data),
                    }
                )
            files[arcname] = data  # 同名附件只保留一份（首见内容）
            if name not in included:
                included.append(name)
            return f"../attachments/{name}"

        def rewrite_embed(match: re.Match[str]) -> str:
            target = _embed_target(match.group(1))
            relative = include(target)
            if relative is None:
                return "<!-- LumiRSS：此处附件未打包（越界/缺失/不允许），详见 manifest violations -->"
            return f"![{Path(target).stem}]({relative})"

        def rewrite_image(match: re.Match[str]) -> str:
            alt, src = match.group(1), match.group(2)
            if _is_remote(src):
                return match.group(0)
            relative = include(src)
            if relative is None:
                return "<!-- LumiRSS：此处附件未打包（越界/缺失/不允许），详见 manifest violations -->"
            return f"![{alt}]({relative})"

        new_text = _EMBED_RE.sub(rewrite_embed, text)
        new_text = _MD_IMAGE_RE.sub(rewrite_image, new_text)
        return new_text, included

    def _final_boundary_check(
        self, files: dict[str, bytes]
    ) -> list[dict[str, str]]:
        """终检：包内任何笔记不得残留越界文件引用（双保险）。

        引用按其在包内的位置解析（notes/<名>.md 的相对目标 → 包根下
        归一化）；解析后越出包根（仍带 ..）、绝对路径、file: → 违规。
        ``../attachments/<名>`` 是正确的包内相对链接，不违规。"""
        violations: list[dict[str, str]] = []
        for arcname, data in files.items():
            text = data.decode("utf-8", errors="replace")
            base_dir = posixpath.dirname(arcname)
            for match in _MD_IMAGE_RE.finditer(text):
                src = match.group(2).strip()
                if _is_remote(src) or src.startswith("#"):
                    continue
                if src.startswith("/") or "\\\\" in src or src.lower().startswith("file:"):
                    violations.append(
                        {
                            "kind": "out_of_bounds_reference",
                            "detail": f"终检发现 {arcname} 残留越界引用 {src}（绝对路径不允许）。",
                        }
                    )
                    continue
                resolved = posixpath.normpath(posixpath.join(base_dir, src))
                if resolved.startswith("..") or resolved == "." :
                    violations.append(
                        {
                            "kind": "out_of_bounds_reference",
                            "detail": f"终检发现 {arcname} 残留越界引用 {src}（越出包根）。",
                        }
                    )
        return violations

    def build_zip(self, manifest: dict[str, Any], files: dict[str, bytes]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
            for arcname in sorted(files):
                bundle.writestr(arcname, files[arcname])
            bundle.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
        return buffer.getvalue()

    async def persist(self, manifest: dict[str, Any]) -> str:
        bundle_id = str(_uuid.uuid4())
        manifest["id"] = bundle_id
        await self._db.execute(
            "INSERT INTO obsidian_portable_bundles (id, notes_json, attachments_json, violations_json, note_count, attachment_count, violation_count, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                bundle_id,
                json.dumps(manifest["notes"], ensure_ascii=False),
                json.dumps(manifest["attachments"], ensure_ascii=False),
                json.dumps(manifest["violations"], ensure_ascii=False),
                manifest["noteCount"],
                manifest["attachmentCount"],
                manifest["violationCount"],
                manifest["createdAt"],
            ),
        )
        return bundle_id

    async def list_bundles(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, note_count, attachment_count, violation_count, created_at"
            " FROM obsidian_portable_bundles ORDER BY created_at DESC, id DESC LIMIT 50"
        )
        return [
            {
                "id": str(row["id"]),
                "noteCount": int(row["note_count"]),
                "attachmentCount": int(row["attachment_count"]),
                "violationCount": int(row["violation_count"]),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]

    async def get_bundle(self, bundle_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT notes_json, attachments_json, violations_json, created_at"
            " FROM obsidian_portable_bundles WHERE id = ?",
            (str(bundle_id).strip(),),
        )
        if row is None:
            return None
        try:
            notes = json.loads(str(row["notes_json"] or "[]"))
        except json.JSONDecodeError:
            notes = []
        try:
            attachments = json.loads(str(row["attachments_json"] or "[]"))
        except json.JSONDecodeError:
            attachments = []
        try:
            violations = json.loads(str(row["violations_json"] or "[]"))
        except json.JSONDecodeError:
            violations = []
        return {
            "id": str(bundle_id).strip(),
            "notes": notes if isinstance(notes, list) else [],
            "attachments": attachments if isinstance(attachments, list) else [],
            "violations": violations if isinstance(violations, list) else [],
            "noteCount": len(notes) if isinstance(notes, list) else 0,
            "attachmentCount": len(attachments) if isinstance(attachments, list) else 0,
            "violationCount": len(violations) if isinstance(violations, list) else 0,
            "createdAt": str(row["created_at"]),
        }
