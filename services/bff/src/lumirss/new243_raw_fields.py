"""NEW-243 原始 feed 字段查看器 —— 脱敏原始字段 + 应用映射 + 错误映射报告。

语义边界（模块存在的理由）：

- 查看器是**派生读**：字段值来自 search_entries 投影（FreshRSS 摄取
  的落库形态），查询时聚合，绝不 shadow-copy、不落库；
- 脱敏规则（保守）：
  * url：只保留 scheme + host + path（query 可能携带令牌，一律隐去）；
  * content_text：不回传正文，只回传长度 + sha256 前 16 位（字段存不
    存在、规模多大可判断，内容不外泄查看器表面）;
  * 其余字段（title/author/published_at/feed_*）原样展示（本就是
    feed 声明的公开元数据）；
- appMapping：每个字段说明应用把它映射成了什么（例如 author →
  阅读列表作者列），这是「应用解释」，不是上游原始语义；用户可以
  报告「这个映射不对」；
- 报告（raw_field_reports）是唯一持久化面：只追加台账，逐条可见，
  不自动改任何映射；没有报告 = 没有争议，不编造默认结论。

投影中没有该条 → 404 raw_fields_not_found（诚实：没有数据可看）。
per-user 库：报告天然按账户隔离。
"""

import hashlib
import sqlite3
import uuid as _uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now

_REPORT_MAX = 2000  # problem / expected 单字段长度上限
_MAX_FEED_URL_DISPLAY = 300

_FIELD_MAPPINGS: tuple[dict[str, str], ...] = (
    {
        "key": "title",
        "mapping": "上游 item 标题 → 阅读列表标题列与文章页 H1",
        "source": "feed 声明的条目标题（FreshRSS 摄取）",
    },
    {
        "key": "author",
        "mapping": "上游 item 作者 → 阅读列表作者列（空串 = 上游未提供）",
        "source": "feed 声明的作者字段",
    },
    {
        "key": "url",
        "mapping": "上游 item 链接 → 「打开原文」外链（查看器只显示 host+path）",
        "source": "feed 声明的条目链接",
    },
    {
        "key": "published_at",
        "mapping": "feed 声明的发表时间 → 排序与来源时间轴的「发表」项",
        "source": "feed 声明（Lumi 未独立验证）",
    },
    {
        "key": "feed_title",
        "mapping": "订阅源标题 → 来源徽标与分组显示",
        "source": "订阅列表里的 feed 标题",
    },
    {
        "key": "content_text",
        "mapping": "上游 item 正文 → 阅读器正文渲染（此处只显示长度与指纹）",
        "source": "feed 声明的正文（摄取时提取纯文本）",
    },
)


class RawFieldInvalid(ValueError):
    """报告负载非法（映射 422）。"""


class RawFieldsNotFound(Exception):
    """投影中没有这篇文章（映射 404）。"""


def _sanitize_url(url: str) -> str:
    """scheme + host + path；query/fragment 一律隐去（可能含令牌）。"""
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return "(无法解析的 URL)"
    if not parts.scheme or not parts.hostname:
        return "(非绝对 URL)"
    shown = f"{parts.scheme}://{parts.hostname}{parts.path or '/'}"
    if len(shown) > _MAX_FEED_URL_DISPLAY:
        shown = shown[:_MAX_FEED_URL_DISPLAY] + "…"
    return shown


def _content_digest(content_text: str) -> dict[str, Any]:
    return {
        "present": content_text != "",
        "chars": len(content_text),
        "sha256Prefix": hashlib.sha256(content_text.encode("utf-8")).hexdigest()[:16]
        if content_text
        else None,
    }


def build_raw_fields(row: Any) -> dict[str, Any]:
    """search_entries 行 → 脱敏字段视图 + 应用映射说明（纯函数）。"""
    fields: list[dict[str, Any]] = []
    for spec in _FIELD_MAPPINGS:
        key = spec["key"]
        if key == "url":
            raw_value = str(row["url"] or "")
            display: Any = _sanitize_url(raw_value) if raw_value else None
        elif key == "content_text":
            raw_value = str(row["content_text"] or "")
            display = _content_digest(raw_value)
        else:
            raw_value = str(row[key] or "")
            display = raw_value if raw_value else None
        fields.append(
            {
                "key": key,
                "value": display,
                "present": raw_value != "",
                "appMapping": spec["mapping"],
                "sourceDescription": spec["source"],
            }
        )
    return {"entryRef": str(row["entry_ref"]), "fields": fields}


class RawFieldStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_fields(self, entry_ref: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT entry_ref, title, author, url, published_at, feed_title, content_text "
            "FROM search_entries WHERE entry_ref = ?",
            (entry_ref,),
        )
        if row is None:
            raise RawFieldsNotFound(entry_ref)
        return build_raw_fields(row)

    # -- 错误映射报告 -------------------------------------------------------

    @staticmethod
    def _validate_text(value: Any, name: str, *, allow_empty: bool = False) -> str:
        if not isinstance(value, str):
            raise RawFieldInvalid(f"{name} 必须是字符串。")
        cleaned = value.strip()
        if len(cleaned) > _REPORT_MAX:
            raise RawFieldInvalid(f"{name} 超出 {_REPORT_MAX} 字符上限。")
        if not allow_empty and not cleaned:
            raise RawFieldInvalid(f"{name} 不能为空。")
        return cleaned

    async def add_report(
        self, entry_ref: str, field_key: str, problem: str, expected: str
    ) -> dict[str, Any]:
        clean_field = self._validate_text(field_key, "fieldKey")
        clean_problem = self._validate_text(problem, "problem")
        clean_expected = self._validate_text(expected, "expected", allow_empty=True)
        report_id = str(_uuid.uuid4())
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO raw_field_reports (id, entry_ref, field_key, problem, expected, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (report_id, entry_ref, clean_field, clean_problem, clean_expected, now),
            )

        await transaction(self._db, _tx)
        return {
            "id": report_id,
            "entryRef": entry_ref,
            "fieldKey": clean_field,
            "problem": clean_problem,
            "expected": clean_expected,
            "createdAt": now,
        }

    async def list_reports(self, entry_ref: str) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, field_key, problem, expected, created_at FROM raw_field_reports "
            "WHERE entry_ref = ? ORDER BY created_at DESC, rowid DESC",
            (entry_ref,),
        )
        return [
            {
                "id": str(row["id"]),
                "fieldKey": str(row["field_key"]),
                "problem": str(row["problem"]),
                "expected": str(row["expected"]),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]
