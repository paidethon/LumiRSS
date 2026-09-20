"""F033 快照资源诊断 + F034 快照版本 —— snapshot_versions 的 SQL 唯一入口。

- resources：每次采集记录的资源状态（页面 ok/failed + 提取出的子资源
  skipped，monolith 单文件化内联、不单独抓取）；有界 ≤200 条，超出
  截断并标记 truncated；
- versions：同一快照的历次采集（sha256 + 净化后纯文本），最多 5 版
  FIFO；内容与最新版相同 → deduped（不新增版本行）。
"""

import difflib
import json
import re
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_RESOURCE_ROWS = 200
_MAX_VERSIONS = 5
_SRC_RE = re.compile(
    r"""(?:src|href)\s*=\s*["']([^"']+)["']""", re.IGNORECASE
)


def extract_resource_urls(html: str, page_url: str) -> dict[str, Any]:
    """页面 ok + 子资源 skipped（有界、去重；超出标记 truncated）。"""
    urls: list[str] = []
    seen: set[str] = set()
    for match in _SRC_RE.finditer(html or ""):
        url = match.group(1).strip()
        if not url or url.startswith(("data:", "#", "javascript:")):
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= _MAX_RESOURCE_ROWS:
            break
    truncated = len(seen) >= _MAX_RESOURCE_ROWS
    resources: list[dict[str, Any]] = [{"url": page_url, "status": "ok"}]
    resources.extend({"url": u, "status": "skipped"} for u in urls)
    return {
        "resources": resources,
        "truncated": truncated,
    }


async def save_resources(
    db: Database, asset_uuid: str, resources: list[dict[str, Any]], truncated: bool
) -> None:
    """资源状态写回快照行（JSON 列；有界）。"""
    await db.migrate()
    await db.execute(
        "UPDATE library_assets SET resources = ?, resources_truncated = ? WHERE uuid = ?",
        (
            json.dumps(resources[:_MAX_RESOURCE_ROWS], ensure_ascii=False),
            1 if truncated else 0,
            asset_uuid,
        ),
    )


def parse_resources(raw: str | None) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw or "[]")
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def text_diff(text_a: str, text_b: str) -> str:
    """逐行 unified 文本差异（stdlib difflib；纯文本输出）。"""
    return "\n".join(
        difflib.unified_diff(
            (text_a or "").splitlines(),
            (text_b or "").splitlines(),
            fromfile="a",
            tofile="b",
            lineterm="",
        )
    )


_COLUMNS = "id, snapshot_uuid, sha256, text, created_at"


class SnapshotVersionStore:
    """版本落库 / 列表 / 读取（内联 SQL + 绑定参数；写站点 ≤2）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record_version(
        self, *, snapshot_uuid: str, sha256: str, text: str
    ) -> dict[str, Any]:
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO snapshot_versions (snapshot_uuid, sha256, text, created_at) VALUES (?, ?, ?, ?)",
            (snapshot_uuid, sha256, text[:200_000], utc_now()),
        )
        # FIFO 淘汰：保留最新 _MAX_VERSIONS 版（id 降序第 N-5 之后的删）。
        stale = await self._db.fetch_all(
            "SELECT id FROM snapshot_versions WHERE snapshot_uuid = ? ORDER BY id DESC LIMIT -1 OFFSET ?",
            (snapshot_uuid, _MAX_VERSIONS),
        )
        for row in stale:
            await self._db.execute(
                "DELETE FROM snapshot_versions WHERE id = ?", (row["id"],)
            )
        row = await self._db.fetch_one(
            f"SELECT {_COLUMNS} FROM snapshot_versions WHERE snapshot_uuid = ? ORDER BY id DESC LIMIT 1",
            (snapshot_uuid,),
        )
        assert row is not None
        return self._row(row)

    async def latest_sha(self, snapshot_uuid: str) -> str | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT sha256 FROM snapshot_versions WHERE snapshot_uuid = ? ORDER BY id DESC LIMIT 1",
            (snapshot_uuid,),
        )
        return str(row["sha256"]) if row is not None else None

    async def list_versions(self, snapshot_uuid: str) -> list[dict[str, Any]]:
        """旧→新。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            f"SELECT {_COLUMNS} FROM snapshot_versions WHERE snapshot_uuid = ? ORDER BY id ASC",
            (snapshot_uuid,),
        )
        return [self._row(row) for row in rows]

    async def get_version(self, version_id: int) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            f"SELECT {_COLUMNS} FROM snapshot_versions WHERE id = ?", (version_id,)
        )
        return self._row(row) if row is not None else None

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        return {
            "versionId": int(row["id"]),
            "snapshotUuid": str(row["snapshot_uuid"]),
            "sha256": str(row["sha256"]),
            "text": str(row["text"] or ""),
            "createdAt": str(row["created_at"]),
        }
