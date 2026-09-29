"""NEW-311 浏览器书签目录导入 —— 预览目录映射与重复链接，再形成资料集合。

诚实口径（与既有 /library/bookmarks/import 一脉相承）：

- 解析复用 bookmarks_io.parse_netscape（本人导出的 Netscape HTML 按
  不可信输入对待：体积/条数上限在路由层强制，坏行跳过不致命）；
- 预览零写入：目录映射（文件夹路径 → 条数）、重复链接（文件内重复
  + 库内已存在，分别标注）、无效条目（scheme/长度）全部如实列出；
- 确认导入 = 按用户勾选的目录范围创建书签（复用
  LibraryStore.create_url_bookmark，唯一索引收敛重复 URL），逐条
  状态落台账（imported / duplicate / invalid / excluded），集合行
  记录真实计数——绝不静默吞掉任何一条；
- 默认跳过重复链接；includeDuplicates=true 时显式尝试创建（唯一
  索引仍会收敛为 duplicate，诚实计数）。

per-user：集合台账与书签同在 per-user 库（RoutingDatabase），A 的
导入集合对 B 不可见，A 的库内重复判定也只看 A 自己的书签。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.bookmarks_io import NetscapeBookmark, parse_netscape
from lumirss.library import (
    _MAX_TITLE_LENGTH,
    BookmarkInvalid,
    LibraryStore,
    _validate_bookmark_url,
)
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_IMPORT_ITEMS = 5000
_SQL_CHUNK = 400


class ImportPreviewInvalid(ValueError):
    """预览/确认的输入不可解析或超出上限（映射 400）。"""


def parse_bookmark_file(text: Any) -> list[NetscapeBookmark]:
    """共享入口：解码检查 + 条数上限（预览与确认同一口径）。"""
    if not isinstance(text, str) or not text.strip():
        raise ImportPreviewInvalid("导入文件为空或不是文本。")
    try:
        items = parse_netscape(text)
    except ValueError as exc:
        raise ImportPreviewInvalid(str(exc)) from exc
    if len(items) > _MAX_IMPORT_ITEMS:
        raise ImportPreviewInvalid(
            f"导入文件条目过多（上限 {_MAX_IMPORT_ITEMS} 条）。"
        )
    return items


def _folder_path(folders: list[str]) -> str:
    return " / ".join(folders)


def build_folder_map(items: list[NetscapeBookmark]) -> list[dict[str, Any]]:
    """目录映射：路径 → 条数（按出现顺序聚合，不发明新目录）。"""
    counts: dict[str, int] = {}
    order: list[str] = []
    for item in items:
        path = _folder_path(item.folders)
        if path not in counts:
            order.append(path)
            counts[path] = 0
        counts[path] += 1
    return [
        {"path": path, "count": counts[path]}
        for path in order
    ]


def _in_file_duplicate_urls(
    items: list[NetscapeBookmark],
) -> dict[str, int]:
    """文件内重复：同一 URL 出现 >1 次 → {url: 次数}（保留首现顺序）。"""
    counts: dict[str, int] = {}
    for item in items:
        counts[item.url] = counts.get(item.url, 0) + 1
    return {
        url: count
        for url, count in counts.items()
        if count > 1
    }


def _classify(items: list[NetscapeBookmark]) -> list[dict[str, Any]]:
    """逐条分类：valid（含清洗后 URL）/ invalid（原因）。"""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        try:
            clean_url = _validate_bookmark_url(item.url)
        except BookmarkInvalid as exc:
            rows.append(
                {
                    "url": item.url,
                    "title": item.title,
                    "folder_path": _folder_path(item.folders),
                    "valid": False,
                    "reason": str(exc),
                }
            )
            continue
        duplicate_in_file = clean_url in seen
        seen.add(clean_url)
        rows.append(
            {
                "url": clean_url,
                "title": item.title,
                "folder_path": _folder_path(item.folders),
                "valid": True,
                "duplicateInFile": duplicate_in_file,
                "reason": "",
            }
        )
    return rows


class BookmarkImportSetStore:
    """NEW-311 预览 + 导入集合台账（per-user）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def preview(self, text: str) -> dict[str, Any]:
        """零写入预览：目录映射 / 重复链接（文件内 + 库内）/ 无效条目。"""
        items = parse_bookmark_file(text)
        rows = _classify(items)
        valid_urls = [row["url"] for row in rows if row["valid"]]
        in_library = await self._existing_urls(valid_urls)
        duplicates = [
            {
                "url": row["url"],
                "title": row["title"],
                "folderPath": row["folder_path"],
                "inFile": bool(row["duplicateInFile"]),
                "inLibrary": row["url"] in in_library,
            }
            for row in rows
            if row["valid"] and (row["duplicateInFile"] or row["url"] in in_library)
        ]
        invalid = [
            {"url": row["url"], "title": row["title"], "reason": row["reason"]}
            for row in rows
            if not row["valid"]
        ]
        return {
            "total": len(items),
            "validTotal": len(valid_urls),
            "folderMap": build_folder_map(items),
            "duplicates": duplicates,
            "invalid": invalid,
            "honestyNote": "预览零写入；确认导入只创建勾选目录内的书签，重复链接默认跳过。",
        }

    async def confirm(
        self,
        text: str,
        *,
        folders: list[str],
        include_duplicates: bool,
        source_name: str = "",
    ) -> dict[str, Any]:
        """按勾选目录创建书签并落集合台账；逐条状态如实记录。"""
        items = parse_bookmark_file(text)
        rows = _classify(items)
        selected = set(folders)
        library = LibraryStore(self._db)
        await self._db.migrate()
        set_id = str(_uuid.uuid4())
        now = utc_now()
        imported = skipped = 0
        item_rows: list[tuple[str, str, str, str, str, str]] = []
        for row in rows:
            if not row["valid"]:
                status = "invalid"
            elif row["duplicateInFile"] and not include_duplicates:
                status = "duplicate"
            elif selected and row["folder_path"] not in selected:
                status = "excluded"
            else:
                try:
                    _view, created = await library.create_url_bookmark(
                        row["url"], row["title"][:_MAX_TITLE_LENGTH]
                    )
                except BookmarkInvalid:
                    status = "invalid"
                else:
                    status = "imported" if created else "duplicate"
            if status == "imported":
                imported += 1
            else:
                skipped += 1
            item_rows.append(
                (str(_uuid.uuid4()), set_id, row["url"], row["title"],
                 row["folder_path"], status)
            )

        def _tx(conn: Any) -> None:
            conn.execute(
                "INSERT INTO bookmark_import_sets (id, source_name, total, imported, skipped, folders_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (set_id, source_name, len(rows), imported, skipped,
                 json.dumps(sorted(selected), ensure_ascii=False), now),
            )
            for row in item_rows:
                conn.execute(
                    "INSERT INTO bookmark_import_set_items (id, set_id, url, title, folder_path, status, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (*row, now),
                )

        from lumirss.db_tx import transaction

        await transaction(self._db, _tx)
        return {
            "id": set_id,
            "sourceName": source_name,
            "total": len(rows),
            "imported": imported,
            "skipped": skipped,
            "folders": sorted(selected),
            "statuses": {
                status: sum(1 for r in item_rows if r[5] == status)
                for status in ("imported", "duplicate", "invalid", "excluded")
            },
        }

    async def list_sets(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, source_name, total, imported, skipped, folders_json, created_at"
            " FROM bookmark_import_sets ORDER BY created_at DESC, id DESC LIMIT 100"
        )
        return [self._set_row(row) for row in rows]

    async def get_set(self, set_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, source_name, total, imported, skipped, folders_json, created_at"
            " FROM bookmark_import_sets WHERE id = ?",
            (set_id,),
        )
        if row is None:
            return None
        result = self._set_row(row)
        item_rows = await self._db.fetch_all(
            "SELECT url, title, folder_path, status FROM bookmark_import_set_items"
            " WHERE set_id = ? ORDER BY created_at ASC, id ASC LIMIT 500",
            (set_id,),
        )
        result["items"] = [
            {
                "url": str(r["url"]),
                "title": str(r["title"]),
                "folderPath": str(r["folder_path"]),
                "status": str(r["status"]),
            }
            for r in item_rows
        ]
        return result

    async def _existing_urls(self, urls: list[str]) -> set[str]:
        """库内已存在的 URL（本账户）；分块查询以绑定参数上限为界。"""
        existing: set[str] = set()
        for start in range(0, len(urls), _SQL_CHUNK):
            chunk = urls[start : start + _SQL_CHUNK]
            placeholders = ",".join("?" for _ in chunk)
            rows = await self._db.fetch_all(
                f"SELECT url FROM library_bookmarks WHERE url IN ({placeholders})",
                tuple(chunk),
            )
            existing.update(str(r["url"]) for r in rows)
        return existing

    @staticmethod
    def _set_row(row: Any) -> dict[str, Any]:
        try:
            folders = json.loads(str(row["folders_json"]))
        except json.JSONDecodeError:
            folders = []
        return {
            "id": str(row["id"]),
            "sourceName": str(row["source_name"]),
            "total": int(row["total"]),
            "imported": int(row["imported"]),
            "skipped": int(row["skipped"]),
            "folders": folders if isinstance(folders, list) else [],
            "createdAt": str(row["created_at"]),
        }
