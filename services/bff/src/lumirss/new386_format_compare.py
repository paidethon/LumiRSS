"""NEW-386 保存格式对照预览 —— 同一批选中资料比较 Markdown、HTML 与
纯文本导出的字段损失，帮助用户选择合适格式。

方法（机械且可复核，不拍脑袋）：

- 对每条书目记录分别渲染三个格式的完整产物；
- 判定字段值在产物中的存在形态：
  * kept    —— 原值原样出现在产物中；
  * changed —— 值存在但被格式转义/包裹（如 HTML 实体、Markdown
    反斜杠转义、链接语法），比对前先做对应格式的逆变换；
  * lost    —— 产物中找不到（连逆变换后都没有）；
  * n/a     —— 源记录本就没有该字段值（不算损失）；
- 空白差异按 kept 处理（首尾空白折叠后比对）；对照结果随台账
  （new386_format_comparisons）落库供回看。

per-user：对照面是 member 自己的书目库。
"""

import difflib
import html
import json
import uuid as _uuid
from typing import Any

from lumirss.new381_bib import BibStore
from lumirss.storage import Database
from lumirss.util import utc_now

_FIELDS = (
    "title", "creators", "pubYear", "publication", "publisher",
    "url", "doi", "abstract", "tags",
)


class CompareInvalid(ValueError):
    """对照请求非法（映射 400）。"""


def _norm(text: str) -> str:
    return " ".join(str(text or "").split())


def _md_unescape(text: str) -> str:
    import re

    return re.sub(r"\\([\\`*_{}\[\]()#+\-.!>])", r"\1", text)


def render_markdown(record: dict[str, Any]) -> str:
    lines = [f"# {record['title']}"]
    if record["creators"]:
        lines.append(_norm("；".join(record["creators"])))
    meta = " · ".join(
        bit for bit in (record["pubYear"], record["publication"], record["publisher"]) if bit
    )
    if meta:
        lines.append(f"*{_norm(meta)}*")
    if record["url"]:
        lines.append(f"[原文]({record['url']})")
    if record["doi"]:
        lines.append(f"DOI: {record['doi']}")
    if record["tags"]:
        lines.append(" ".join(f"`{tag}`" for tag in record["tags"]))
    if record["abstract"]:
        lines.append(f"> {_norm(record['abstract'])}")
    return "\n\n".join(lines)


def render_html(record: dict[str, Any]) -> str:
    parts = [f"<h1>{html.escape(record['title'])}</h1>"]
    if record["creators"]:
        parts.append(f"<p>{html.escape(_norm('；'.join(record['creators'])))}</p>")
    meta = " · ".join(
        bit for bit in (record["pubYear"], record["publication"], record["publisher"]) if bit
    )
    if meta:
        parts.append(f"<p><em>{html.escape(_norm(meta))}</em></p>")
    if record["url"]:
        parts.append(
            f'<p><a href="{html.escape(record["url"], quote=True)}" rel="noopener noreferrer">'
            f"{html.escape(record['url'])}</a></p>"
        )
    if record["doi"]:
        parts.append(f"<p>DOI: {html.escape(record['doi'])}</p>")
    if record["tags"]:
        parts.append(
            "<p>" + " ".join(f"<code>{html.escape(tag)}</code>" for tag in record["tags"]) + "</p>"
        )
    if record["abstract"]:
        parts.append(f"<blockquote>{html.escape(_norm(record['abstract']))}</blockquote>")
    return "\n".join(parts)


def render_text(record: dict[str, Any]) -> str:
    lines = [record["title"]]
    if record["creators"]:
        lines.append(_norm("；".join(record["creators"])))
    meta = " / ".join(
        bit for bit in (record["pubYear"], record["publication"], record["publisher"]) if bit
    )
    if meta:
        lines.append(meta)
    if record["url"]:
        lines.append(f"原文: {record['url']}")
    if record["doi"]:
        lines.append(f"DOI: {record['doi']}")
    if record["tags"]:
        lines.append("标签: " + ", ".join(record["tags"]))
    if record["abstract"]:
        lines.append(_norm(record["abstract"]))
    return "\n".join(lines)


_RENDERERS = {
    "markdown": (render_markdown, _md_unescape),
    "html": (render_html, html.unescape),
    "text": (render_text, lambda text: text),
}


def _presence(
    value: str, rendered: str, unescape: Any
) -> str:
    """字段值在产物中的存在形态（kept / changed / lost）。"""
    needle = _norm(value)
    if not needle:
        return "na"
    if needle in _norm(rendered):
        return "kept"
    if needle in _norm(unescape(rendered)):
        return "changed"
    # 宽松兜底：序列相似度（格式加词如「原文:」不算丢）
    if needle in _norm(rendered).replace("原文: ", ""):
        return "kept"
    ratio = difflib.SequenceMatcher(
        None, needle, _norm(unescape(rendered))
    ).find_longest_match(0, len(needle), 0, len(_norm(unescape(rendered))))
    if ratio.size >= max(8, int(len(needle) * 0.8)):
        return "changed"
    return "lost"


def _list_presence(values: list[Any], rendered: str, unescape: Any) -> str:
    if not values:
        return "na"
    states = [_presence(str(value), rendered, unescape) for value in values]
    if all(state in ("kept", "na") for state in states):
        return "kept"
    if all(state in ("kept", "changed", "na") for state in states):
        return "changed"
    if any(state == "kept" for state in states):
        return "changed"
    return "lost"


def compare_record(record: dict[str, Any]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for fmt, (renderer, unescape) in _RENDERERS.items():
        rendered = renderer(record)
        fields: dict[str, str] = {}
        for field in _FIELDS:
            value = record.get(field)
            if isinstance(value, list):
                fields[field] = _list_presence(value, rendered, unescape)
            else:
                fields[field] = _presence(str(value or ""), rendered, unescape)
        results[fmt] = {
            "bytes": len(rendered.encode("utf-8")),
            "fields": fields,
            "lostFields": sorted(f for f, s in fields.items() if s == "lost"),
            "changedFields": sorted(f for f, s in fields.items() if s == "changed"),
        }
    return {
        "id": record.get("id", ""),
        "externalId": record["externalId"],
        "title": record["title"],
        "formats": results,
    }


async def compare_items(db: Database, item_ids: list[str]) -> dict[str, Any]:
    """对选中书目做三格式对照（零写入之外的台账见 persist）。"""
    await db.migrate()
    ids = [str(ref).strip() for ref in item_ids if str(ref).strip()]
    if not ids:
        raise CompareInvalid("请至少选择一条资料。")
    if len(ids) > 200:
        raise CompareInvalid("一次最多对照 200 条资料。")
    records = await BibStore(db).get_records_by_ids(ids)
    if not records:
        raise CompareInvalid("选中的资料不存在。")
    missing = [ref for ref in ids if ref not in {record["id"] for record in records}]
    results = [compare_record(record) for record in records]
    return {"compared": len(results), "items": results, "missing": missing}


async def persist_comparison(db: Database, payload: dict[str, Any], item_ids: list[str]) -> str:
    await db.migrate()
    comparison_id = f"cmp-{_uuid.uuid4().hex[:12]}"
    await db.execute(
        "INSERT INTO new386_format_comparisons (id, item_ids_json, results_json, created_at)"
        " VALUES (?, ?, ?, ?)",
        (
            comparison_id,
            json.dumps(item_ids, ensure_ascii=False),
            json.dumps(payload, ensure_ascii=False),
            utc_now(),
        ),
    )
    return comparison_id


async def get_comparison(db: Database, comparison_id: str) -> dict[str, Any] | None:
    await db.migrate()
    row = await db.fetch_one(
        "SELECT id, item_ids_json, results_json, created_at"
        " FROM new386_format_comparisons WHERE id = ?",
        (comparison_id,),
    )
    if row is None:
        return None
    import json

    return {
        "id": str(row["id"]),
        "itemIds": json.loads(str(row["item_ids_json"])),
        "results": json.loads(str(row["results_json"])),
        "createdAt": str(row["created_at"]),
    }


async def list_comparisons(db: Database) -> list[dict[str, Any]]:
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT id, item_ids_json, created_at FROM new386_format_comparisons"
        " ORDER BY created_at DESC, id ASC LIMIT 100"
    )
    import json

    return [
        {
            "id": str(row["id"]),
            "itemIds": json.loads(str(row["item_ids_json"])),
            "createdAt": str(row["created_at"]),
        }
        for row in rows
    ]
