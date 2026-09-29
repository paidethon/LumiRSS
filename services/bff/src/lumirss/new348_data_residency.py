"""NEW-348 数据驻留说明页 —— 按「实际配置」展示正文、备份、AI 请求
与遥测在哪里处理；未知项明确标 unknown 并提示管理员补充。

诚实口径：
- 每个固定键的 detail 从当前真实配置推导（FreshRSS/RSSHub 实例、
  AI provider、WebDAV、遥测=无）；推导不出事实的键如实标
  ``unknown=true``（附「请管理员补充」提示），绝不编造驻留地；
- 管理员注释（residency_notes，0271，实例级存控制库）只允许管理员
  写；成员只读 —— 注释是运营者对部署事实的补充说明，不是系统
  自动探测；
- 遥测：Lumi 不内置任何遥测/统计上报 —— 这条按「实际构建」如实
  返回 known（detail 固定），无需管理员补充。

per-user：说明是实例级的（控制库 notes）；成员请求合并自己可见的
配置推导（AI host 等读取与 FIX-148 data-flows 同源）。
"""

import re
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

FIXED_KEYS: tuple[tuple[str, str, str], ...] = (
    ("article_body", "文章正文", "FreshRSS 实例存储正文；Lumi 保存搜索投影副本（本机 per-user 库）"),
    ("backups", "备份", "备份包写入位置由备份配置决定（本机目录或 WebDAV 目标）"),
    ("ai_requests", "AI 请求", "摘要/对话/翻译文本发往 AI 设置里配置的 provider"),
    ("telemetry", "遥测", "Lumi 不内置遥测/统计上报：无任何使用数据外发"),
    ("freshrss_instance", "FreshRSS 实例", "订阅、条目与已读/收藏状态的权威存储"),
    ("rsshub_instance", "RSSHub 实例", "非 RSS 源的内容生成服务"),
)

NOTE_KEY_PATTERN = re.compile(r"^[a-z0-9_]{1,40}$")
MAX_NOTE_CHARS = 500


class ResidencyNoteInvalid(ValueError):
    """注释负载非法（映射 422）。"""


def clean_note_key(raw: Any) -> str:
    if not isinstance(raw, str) or not NOTE_KEY_PATTERN.match(raw):
        raise ResidencyNoteInvalid("key 必须匹配 ^[a-z0-9_]{1,40}$。")
    return raw


def clean_note_text(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ResidencyNoteInvalid("note 必须是非空字符串。")
    text = raw.strip()
    if len(text) > MAX_NOTE_CHARS:
        raise ResidencyNoteInvalid(f"note 最长 {MAX_NOTE_CHARS} 字符。")
    return text


class ResidencyNoteStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(self, key: str, note: str, updated_by: str) -> dict[str, Any]:
        clean_key = clean_note_key(key)
        clean_note = clean_note_text(note)
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO residency_notes (key, note, updated_by, updated_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET note = excluded.note,"
            " updated_by = excluded.updated_by, updated_at = excluded.updated_at",
            (clean_key, clean_note, updated_by, utc_now()),
        )
        return {"key": clean_key, "note": clean_note, "updatedBy": updated_by}

    async def all_notes(self) -> dict[str, dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT key, note, updated_by, updated_at FROM residency_notes"
        )
        return {
            str(row["key"]): {
                "note": str(row["note"]),
                "updatedBy": str(row["updated_by"]),
                "updatedAt": str(row["updated_at"]),
            }
            for row in rows
        }

    async def delete(self, key: str) -> bool:
        clean_key = clean_note_key(key)
        import sqlite3

        from lumirss.db_tx import transaction

        def _tx(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute(
                "DELETE FROM residency_notes WHERE key = ?", (clean_key,)
            )
            return bool(cursor.rowcount)

        return bool(await transaction(self._db, _tx))


def build_residency_view(
    *,
    freshrss_host: str | None,
    rsshub_host: str | None,
    ai_host: str | None,
    webdav_host: str | None,
    webdav_ready: bool,
    notes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """纯函数组装：推导事实 + 管理员注释 + 未知项如实标注。"""

    def section(key: str, title: str, derived: str, known: bool) -> dict[str, Any]:
        note = notes.get(key)
        return {
            "key": key,
            "title": title,
            "detail": derived,
            "known": known,
            "adminNote": note["note"] if note else None,
            "adminNoteUpdatedAt": note["updatedAt"] if note else None,
        }

    sections = [
        section(
            "article_body",
            "文章正文",
            f"FreshRSS 实例（{freshrss_host}）存储正文；Lumi 另存本机搜索投影副本"
            if freshrss_host
            else "FreshRSS 未配置（无法推导正文驻留）",
            freshrss_host is not None,
        ),
        section(
            "backups",
            "备份",
            f"服务器端备份上传 WebDAV（{webdav_host}）"
            if webdav_ready and webdav_host
            else "未配置远程备份目标；本机备份写在部署的 data 目录（具体磁盘/托管由部署决定）",
            webdav_ready and webdav_host is not None,
        ),
        section(
            "ai_requests",
            "AI 请求",
            f"摘要/对话/翻译文本发往 provider（{ai_host}）"
            if ai_host
            else "未配置外部 AI：无 AI 文本外发（翻译可走本地引擎/浏览器能力）",
            True,
        ),
        section(
            "telemetry",
            "遥测",
            "Lumi 不内置遥测/统计上报：无任何使用数据外发",
            True,
        ),
        section(
            "freshrss_instance",
            "FreshRSS 实例",
            f"订阅、条目与已读/收藏状态在 FreshRSS（{freshrss_host}）"
            if freshrss_host
            else "FreshRSS 未配置（无法推导）",
            freshrss_host is not None,
        ),
        section(
            "rsshub_instance",
            "RSSHub 实例",
            f"非 RSS 源由 RSSHub（{rsshub_host}）生成"
            if rsshub_host
            else "未配置 RSSHub：非 RSS 源不可用（无相关请求）",
            rsshub_host is not None,
        ),
    ]
    unknown = [s["key"] for s in sections if not s["known"]]
    return {
        "sections": sections,
        "unknownKeys": unknown,
        "unknownHint": "标记为未知的项无法从配置推导，请管理员在管理端补充驻留说明。",
        "noteKeysHint": "管理员注释键：固定键或 ^[a-z0-9_]{1,40}$ 自定义键（如 hosting_provider）。",
    }
