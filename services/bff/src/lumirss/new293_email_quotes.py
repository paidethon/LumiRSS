"""NEW-293 邮件引用折叠 —— 阅读导入邮件时收起重复引用的前文，
用户可逐段展开核对。

诚实口径（硬规则）：

- 分段是行前缀启发式（"> "开头的行 = 引用段；连续同类行合并为一段），
  绝不声称语义级还原引用归属；"On ... wrote:" 一类无前缀标记不在本版
  识别范围（honestyNote 随响应如实说明）；
- 折叠只影响阅读视图：原文分毫不动地存在 email_materials，展开任一
  段都能看到完整内容（逐段核对）；
- 「已核对」是用户显式标记，按 (material_id, segment_index) 存于
  per-user 库——它只表示「我看过了」，不改变任何内容。

per-user：核对标记在 per-user 库，A 的核对状态对 B 不可见。
"""

from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

HONESTY_NOTE = (
    "分段按行前缀（“>”）启发式识别引用；无前缀的引用写法不在识别范围。"
    "折叠只影响阅读视图，原文始终完整保存，展开即可逐段核对。"
)

_MAX_SEGMENTS = 200


def split_segments(body_text: str) -> list[dict[str, Any]]:
    """把纯文本正文切成 own / quoted 段（行前缀启发式，纯函数）。"""
    segments: list[dict[str, Any]] = []
    kind: str | None = None
    lines: list[str] = []

    def flush() -> None:
        if kind is None or not lines:
            return
        segments.append(
            {
                "index": len(segments),
                "kind": kind,
                "lines": len(lines),
                "text": "\n".join(lines),
            }
        )

    for line in str(body_text or "").splitlines():
        current = "quoted" if line.lstrip().startswith(">") else "own"
        if len(segments) + 1 > _MAX_SEGMENTS:
            # 段数封顶：之后全部并入最后一段，绝不假装无截断。
            if segments:
                segments[-1]["text"] += f"\n{line}"
                segments[-1]["lines"] += 1
            continue
        if current != kind:
            flush()
            kind = current
            lines = []
        lines.append(line)
    flush()
    return segments


class SegmentNotFound(LookupError):
    """段索引不存在（映射 404）。"""


class SegmentNotQuoted(ValueError):
    """段不是引用段（映射 422：只有引用段需要核对）。"""


class EmailQuoteStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def segments_view(self, material_id: str) -> dict[str, Any] | None:
        """分段视图 + 每段核对状态（不存在条目 → None）。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT body_text FROM email_materials WHERE id = ?",
            (material_id,),
        )
        if row is None:
            return None
        segments = split_segments(str(row["body_text"]))
        reviewed = {
            int(r["segment_index"])
            for r in await self._db.fetch_all(
                "SELECT segment_index FROM email_quote_reviews WHERE material_id = ?",
                (material_id,),
            )
        }
        for segment in segments:
            segment["reviewed"] = segment["index"] in reviewed
        quoted = [s for s in segments if s["kind"] == "quoted"]
        return {
            "materialId": material_id,
            "segments": segments,
            "quotedCount": len(quoted),
            "quotedLines": sum(int(s["lines"]) for s in quoted),
            "reviewedCount": len(reviewed & {s["index"] for s in quoted}),
            "honestyNote": HONESTY_NOTE,
        }

    async def mark_reviewed(
        self, material_id: str, segment_index: int
    ) -> dict[str, Any]:
        """把一段标为已核对；段必须是真实存在的引用段。"""
        view = await self.segments_view(material_id)
        if view is None:
            raise SegmentNotFound("没有这条邮件资料条目。")
        target = next(
            (s for s in view["segments"] if s["index"] == segment_index), None
        )
        if target is None:
            raise SegmentNotFound("段索引不存在。")
        if target["kind"] != "quoted":
            raise SegmentNotQuoted("该段不是引用段，无需核对。")
        await self._db.execute(
            "INSERT INTO email_quote_reviews (material_id, segment_index,"
            " reviewed_at) VALUES (?, ?, ?)"
            " ON CONFLICT(material_id, segment_index)"
            " DO UPDATE SET reviewed_at = excluded.reviewed_at",
            (material_id, segment_index, utc_now()),
        )
        return await self.segments_view(material_id)  # type: ignore[return-value]
