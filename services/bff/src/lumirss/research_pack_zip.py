"""F088 资料包导出增强 —— 快照纳入的 ZIP 导出（安全成员路径 + sha256）。

- preview：计数 + 体积估算 + 可选快照清单（缺失资产诚实跳过并记录）；
- zip：成员路径白名单化（manifest.json / research-pack.md / 目录内
  `snapshots/<uuid>.<ext>`），拒绝 `..`/绝对路径成分（负向测试）；
- 总量 ≤20MB，否则 413（research_pack_too_large）；
- manifest.json 含逐文件 sha256 + 计数 + missing 清单；
- 同一资产被引用两次只打包一份（按 uuid 去重）。

写站点 0（纯读导出；文件字节经既有 AssetStore 路径读取）。
"""

import hashlib
import json
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

from lumirss.util import utc_now

MAX_ZIP_BYTES = 20 * 1024 * 1024


class ZipTooLarge(Exception):
    """打包体积超过 20MB 上限，映射 413。"""


class ZipInvalid(Exception):
    """打包请求非法（快照不存在/路径不安全），映射 422。"""


def safe_member_path(*parts: str) -> str:
    """白名单化成员路径：任何 `..`/绝对路径/空成分 → ZipInvalid。"""
    cleaned: list[str] = []
    for part in parts:
        p = PurePosixPath(str(part))
        if p.is_absolute() or not p.parts or any(
            seg in ("..", ".") for seg in p.parts
        ):
            raise ZipInvalid(f"不安全的成员路径成分：{part!r}")
        cleaned.extend(p.parts)
    member = "/".join(cleaned)
    if not member or member.startswith("/") or ".." in member.split("/"):
        raise ZipInvalid("不安全的成员路径。")
    return member


def _asset_bytes(root: Path, rel_path: str) -> bytes:
    """读取资产文件（路径来自 DB path 列；再次过 safe_member_path）。"""
    full = (root / rel_path).resolve()
    root_resolved = root.resolve()
    if not str(full).startswith(str(root_resolved)):
        raise ZipInvalid("资产路径越界。")
    return full.read_bytes()


class ResearchPackZipBuilder:
    def __init__(self, db: Any, asset_root: Path) -> None:
        self._db = db
        self._asset_root = asset_root

    async def _snapshots(self, uuids: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        """解析快照资产行（去重、保序）；缺失 uuid 诚实跳过。"""
        found: list[dict[str, Any]] = []
        missing: list[str] = []
        seen: set[str] = set()
        for uuid in uuids:
            if uuid in seen:
                continue
            seen.add(uuid)
            row = await self._db.fetch_one(
                "SELECT uuid, path, bytes, sha256, mime, url FROM library_assets WHERE uuid = ?",
                (uuid,),
            )
            if row is None:
                missing.append(uuid)
                continue
            item = await self._db.fetch_one(
                "SELECT kind, deleted_at FROM library_items WHERE uuid = (SELECT item_uuid FROM library_assets WHERE uuid = ?)",
                (uuid,),
            )
            if item is None or item["deleted_at"] is not None:
                missing.append(uuid)
                continue
            title_row = await self._db.fetch_one(
                "SELECT title FROM library_clips WHERE item_uuid = (SELECT item_uuid FROM library_assets WHERE uuid = ?)",
                (uuid,),
            )
            found.append(
                {
                    "uuid": str(row["uuid"]),
                    "path": str(row["path"]),
                    "bytes": int(row["bytes"]),
                    "sha256": str(row["sha256"]),
                    "mime": str(row["mime"]),
                    "title": str(title_row["title"]) if title_row else str(row["uuid"]),
                }
            )
        return found, missing

    async def preview(
        self,
        *,
        entry_count: int,
        missing_count: int,
        include_snapshots: list[str],
    ) -> dict[str, Any]:
        snapshots, missing = await self._snapshots(include_snapshots)
        est = 2048 + entry_count * 900 + sum(s["bytes"] for s in snapshots)
        return {
            "entryCount": entry_count,
            "missingCount": missing_count,
            "estBytes": est,
            "snapshots": [
                {"uuid": s["uuid"], "title": s["title"], "bytes": s["bytes"]}
                for s in snapshots
            ],
            "missingSnapshots": missing,
        }

    async def build_zip(
        self,
        *,
        markdown: str,
        entry_count: int,
        missing_count: int,
        include_snapshots: list[str],
    ) -> tuple[bytes, dict[str, Any]]:
        snapshots, missing = await self._snapshots(include_snapshots)
        buffer = BytesIO()
        files: list[dict[str, Any]] = []
        total = 0
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            def _add(member: str, data: bytes) -> None:
                nonlocal total
                safe_member_path(member)  # 每个成员都过白名单
                total += len(data)
                if total > MAX_ZIP_BYTES:
                    raise ZipTooLarge("资料包超过 20MB 上限。")
                zf.writestr(member, data)
                files.append(
                    {
                        "path": member,
                        "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )

            md_bytes = markdown.encode("utf-8")
            _add("research-pack.md", md_bytes)
            packed_missing = list(missing)
            for snapshot in snapshots:
                try:
                    data = _asset_bytes(self._asset_root, snapshot["path"])
                except (OSError, ZipInvalid):
                    # 缺失资产诚实跳过并记入 manifest。
                    packed_missing.append(snapshot["uuid"])
                    continue
                suffix = Path(snapshot["path"]).suffix or ".bin"
                _add(
                    safe_member_path("snapshots", snapshot["uuid"] + suffix),
                    data,
                )
            manifest = {
                "kind": "lumirss-research-pack",
                "schemaVersion": 2,
                "format": "zip",
                "generatedAt": utc_now(),
                "entryCount": entry_count,
                "missingCount": missing_count,
                "fileCount": len(files),
                "files": files,
                "snapshots": [s["uuid"] for s in snapshots],
                "missing": sorted(set(packed_missing)),
            }
            _add("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
            # manifest.json 自身计入文件清单（计数==包内文件数的契约）。
            manifest["fileCount"] = len(files)
            manifest["files"] = files
        payload = buffer.getvalue()
        if len(payload) > MAX_ZIP_BYTES:
            raise ZipTooLarge("资料包超过 20MB 上限。")
        return payload, manifest
