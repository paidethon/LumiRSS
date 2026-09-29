r"""NEW-314 网页快照文字检索层 —— 对已保存快照建立可查找文本层。

- 只处理用户已授权保存的快照（library_assets 行 + 落盘文件）——
  构建层是纯读操作：读字节 → 解析文本块 → 写派生表；原快照字节、
  sha256、文件 mtime 都不变（负向断言依赖）；
- 文本块按块级元素切分（p/h1-h6/li/blockquote/pre），``anchor`` 记录
  最近上级标题——搜索命中返回 (seq, anchor, text)，前端按 seq 滚动
  定位，不重新解析 HTML；
- 搜索词按字面匹配（LIKE 转义 %/_/\），命中上限 100 条诚实标注；
  未构建先搜 → 404（提示先构建），绝不返回空结果假装搜过。

per-user：快照与文本层同库（RoutingDatabase），A 的层对 B 不可见。
"""

from html.parser import HTMLParser
from typing import Any

from lumirss.library_assets import AssetStore
from lumirss.storage import Database
from lumirss.util import utc_now

_BLOCK_TAGS = frozenset(
    {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre"}
)
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_MAX_BLOCKS = 5000
_MAX_BLOCK_CHARS = 4000
_MAX_QUERY_CHARS = 200
_MAX_HITS = 100


class TextLayerInvalid(ValueError):
    """搜索词非法（映射 400）。"""


class _BlockParser(HTMLParser):
    """按块级元素收集文本块 + 最近标题锚（只读解析，不改写输入）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, str]] = []
        self._buffer: list[str] | None = None
        self._anchor = ""
        self._anchor_buffer: list[str] | None = None

    def handle_starttag(self, tag, attrs):  # noqa: D401 — parser callback
        lowered = tag.lower()
        if lowered in _HEADING_TAGS:
            self._flush_block()
            self._anchor_buffer = []
            return
        if lowered in _BLOCK_TAGS:
            self._flush_block()
            self._buffer = []

    def handle_endtag(self, tag):  # noqa: D401 — parser callback
        lowered = tag.lower()
        if lowered in _HEADING_TAGS and self._anchor_buffer is not None:
            self._anchor = " ".join("".join(self._anchor_buffer).split())
            self._anchor_buffer = None
            return
        if lowered in _BLOCK_TAGS and self._buffer is not None:
            self._flush_block()

    def handle_data(self, data):  # noqa: D401 — parser callback
        if self._anchor_buffer is not None:
            self._anchor_buffer.append(data)
        if self._buffer is not None:
            self._buffer.append(data)

    def _flush_block(self) -> None:
        if self._buffer is None:
            return
        text = " ".join("".join(self._buffer).split())
        self._buffer = None
        if not text:
            return
        self.blocks.append(
            {"text": text[:_MAX_BLOCK_CHARS], "anchor": self._anchor}
        )

    def result(self) -> list[dict[str, str]]:
        self._flush_block()
        return self.blocks[:_MAX_BLOCKS]


def extract_text_blocks(html_text: str) -> list[dict[str, str]]:
    parser = _BlockParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:  # noqa: BLE001 — 部分块优于整体失败
        pass
    return parser.result()


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SnapshotTextLayerStore:
    """文本层构建 + 检索（per-user，派生数据，可重建）。"""

    def __init__(self, db: Database, assets: AssetStore) -> None:
        self._db = db
        self._assets = assets

    async def build(self, asset_uuid: str) -> dict[str, Any]:
        # 纯读：快照文件字节保持不变（sha256 不变的负向断言依赖）。
        data = await self._assets.read_bytes(asset_uuid)
        try:
            html_text = data.decode("utf-8")
        except UnicodeDecodeError:
            html_text = data.decode("utf-8", errors="replace")
        blocks = extract_text_blocks(html_text)
        await self._db.migrate()
        built_at = utc_now()

        def _tx(conn: Any) -> None:
            conn.execute(
                "DELETE FROM snapshot_text_layers WHERE asset_uuid = ?",
                (asset_uuid,),
            )
            for seq, block in enumerate(blocks):
                conn.execute(
                    "INSERT INTO snapshot_text_layers (asset_uuid, seq, text, anchor, built_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (asset_uuid, seq, block["text"], block["anchor"], built_at),
                )

        from lumirss.db_tx import transaction

        await transaction(self._db, _tx)
        return {
            "assetRef": f"library:{asset_uuid}",
            "blockCount": len(blocks),
            "builtAt": built_at,
        }

    async def search(self, asset_uuid: str, query: str) -> dict[str, Any]:
        clean = (query or "").strip()
        if not clean:
            raise TextLayerInvalid("搜索词不能为空。")
        if len(clean) > _MAX_QUERY_CHARS:
            raise TextLayerInvalid(f"搜索词过长（最多 {_MAX_QUERY_CHARS} 字）。")
        await self._db.migrate()
        status = await self.status(asset_uuid)
        if not status["built"]:
            from lumirss.library_assets import AssetNotFound

            raise AssetNotFound(asset_uuid)
        rows = await self._db.fetch_all(
            "SELECT seq, text, anchor FROM snapshot_text_layers"
            " WHERE asset_uuid = ? AND text LIKE ? ESCAPE '\\'"
            " ORDER BY seq ASC LIMIT ?",
            (asset_uuid, f"%{_escape_like(clean)}%", _MAX_HITS),
        )
        total_row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM snapshot_text_layers"
            " WHERE asset_uuid = ? AND text LIKE ? ESCAPE '\\'",
            (asset_uuid, f"%{_escape_like(clean)}%"),
        )
        total = int(total_row["n"]) if total_row is not None else 0
        return {
            "assetRef": f"library:{asset_uuid}",
            "query": clean,
            "hits": [
                {
                    "seq": int(row["seq"]),
                    "anchor": str(row["anchor"]),
                    "text": str(row["text"]),
                }
                for row in rows
            ],
            "hitCount": total,
            "truncated": total > len(rows),
        }

    async def status(self, asset_uuid: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n, MAX(built_at) AS built_at FROM snapshot_text_layers"
            " WHERE asset_uuid = ?",
            (asset_uuid,),
        )
        count = int(row["n"]) if row is not None else 0
        return {
            "assetRef": f"library:{asset_uuid}",
            "built": count > 0,
            "blockCount": count,
            "builtAt": str(row["built_at"]) if row is not None and row["built_at"] else None,
        }
