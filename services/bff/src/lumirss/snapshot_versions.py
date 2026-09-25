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


# ---- N124：快照资源预算（storage accounting）与选择性清理 --------------------
#
# monolith 单文件化把子资源内联为 base64 data: URI，磁盘上只有一个
# HTML 文件（library_assets.bytes 即其物理大小）。因此：
# - 预算 = 真实文件大小 + 按内联 data: URI 的 MIME 分类（图片/样式/
#   附件）算术拆分（base64 解码长度是纯计算，绝不整包解码）；
# - 清理 = 把选中类别的 data: URI 从文件中移除（条目本体/标题/文本
#   不动），并以「资源完整性清单」（resources 列）里对应 URL 标记为
#   missing 呈现——删除后这些资源就是缺失，如实回显。

_DATA_URI_RE = re.compile(
    r"data:([a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+)[;,]base64,([A-Za-z0-9+/=]+)"
)
_IMAGE_EXTS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif", ".bmp", ".ico",
)
_CLEANUP_KINDS = ("images", "styles", "attachments")


def classify_inline_mime(mime: str) -> str | None:
    """内联 MIME → 预算/清理类别；页面本体（text/html）不属于可清理资源。"""
    mime = mime.partition(";")[0].strip().lower()
    if mime.startswith("image/"):
        return "images"
    if mime == "text/css":
        return "styles"
    if mime == "text/html":
        return None
    return "attachments"


def _base64_decoded_len(payload: str) -> int:
    """base64 载荷的解码后字节数（纯算术；不做实际解码）。"""
    stripped = payload.rstrip("=")
    return len(stripped) * 3 // 4


def _url_kind(url: str) -> str | None:
    """资源 URL → 类别（仅用于把清单条目与清理类别对应；page 本身不匹配）。"""
    path = str(url or "").split("?", 1)[0].split("#", 1)[0].lower()
    if path.endswith(".css"):
        return "styles"
    if path.endswith(_IMAGE_EXTS):
        return "images"
    if path.endswith((".html", ".htm", ".xhtml", "/")):
        return None
    return "attachments"


def storage_breakdown(html: str) -> dict[str, Any]:
    """按内联 data: URI 类别统计字节（images 带计数；styles/attachments 计字节）。"""
    counts: dict[str, dict[str, int]] = {
        "images": {"count": 0, "bytes": 0},
        "styles": {"count": 0, "bytes": 0},
        "attachments": {"count": 0, "bytes": 0},
    }
    for match in _DATA_URI_RE.finditer(html or ""):
        kind = classify_inline_mime(match.group(1))
        if kind is None:
            continue
        counts[kind]["count"] += 1
        counts[kind]["bytes"] += _base64_decoded_len(match.group(2))
    return counts


def strip_inline_resources(html: str, kinds: tuple[str, ...]) -> tuple[str, dict[str, int]]:
    """把选中类别的内联 data: URI 从 HTML 移除。返回 (新 HTML, 每类移除数)。"""
    removed: dict[str, int] = {kind: 0 for kind in _CLEANUP_KINDS}

    def _repl(match: re.Match[str]) -> str:
        kind = classify_inline_mime(match.group(1))
        if kind is not None and kind in kinds:
            removed[kind] += 1
            return ""
        return match.group(0)

    return _DATA_URI_RE.sub(_repl, html or ""), removed


def mark_resources_missing(
    resources: list[dict[str, Any]], kinds: tuple[str, ...]
) -> list[dict[str, Any]]:
    """清单中选中类别的子资源（skipped）标记为 missing；页面行不动。"""
    updated: list[dict[str, Any]] = []
    for item in resources:
        if (
            isinstance(item, dict)
            and item.get("status") == "skipped"
            and _url_kind(str(item.get("url", ""))) in kinds
        ):
            updated.append({**item, "status": "missing"})
        else:
            updated.append(item)
    return updated


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
