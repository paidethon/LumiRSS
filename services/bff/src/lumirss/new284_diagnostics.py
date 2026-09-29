"""NEW-284 简报缺刊诊断 —— 期次生成失败时的具体缺失输入与执行阶段。

生成管线（deterministic，零 AI / 零网络）分三阶段，任何一阶段缺输入
就停在那里，422 带诊断体（stage + missing 清单），同一份诊断落库到
briefing_attempts——用户补输入后重跑，attempts 留下 failed → ok 的
完整轨迹。绝不允许「空白成功页」：

- stage=candidates：窗口未配置 / 范围非法 / 窗口内 0 篇文章；
- stage=sections：配方栏目按规则筛不出任何文章（缺刊如实证出是哪个
  栏目、哪条规则、缺什么输入），用户补星标/来源/范围后重跑；
- stage=assemble：分配后 0 条（防御性兜底）。

成功路径与 283/286/287 协作：窗口迟到条目排除（属下一期，返回
excludedLate 如实报数）、条目 provenance='rule'（规则推荐，编辑可
翻转为人工选入）。

per-user：attempts 在 per-user 库，A 的诊断对 B 不可见。
"""

import json
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from lumirss.new281_briefings import (
    BriefingInvalid,
    BriefingStore,
    make_excerpt,
)
from lumirss.new283_window import BriefingWindowStore
from lumirss.storage import Database
from lumirss.util import utc_now

_ATTEMPT_LIMIT = 50


class AttemptStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        *,
        stage: str,
        status: str,
        inputs: dict[str, Any],
        missing: list[dict[str, str]],
        detail: str,
    ) -> dict[str, Any]:
        await self._db.migrate()
        attempt_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO briefing_attempts (id, stage, status, inputs_json,"
            " missing_json, detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                attempt_id,
                stage,
                status,
                json.dumps(inputs, ensure_ascii=False),
                json.dumps(missing, ensure_ascii=False),
                detail,
                now,
            ),
        )
        return {
            "id": attempt_id,
            "stage": stage,
            "status": status,
            "inputs": inputs,
            "missing": missing,
            "detail": detail,
            "createdAt": now,
        }

    async def list_attempts(self, *, limit: int = 20) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, stage, status, inputs_json, missing_json, detail,"
            " created_at FROM briefing_attempts"
            " ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (max(1, min(int(limit), _ATTEMPT_LIMIT)),),
        )
        return [
            {
                "id": str(row["id"]),
                "stage": str(row["stage"]),
                "status": str(row["status"]),
                "inputs": json.loads(str(row["inputs_json"] or "{}")),
                "missing": json.loads(str(row["missing_json"] or "[]")),
                "detail": str(row["detail"]),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]


def _parse_bound(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BriefingInvalid(f"{field} 必填（ISO 时间）。")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BriefingInvalid(f"{field} 不是合法 ISO 时间：{text}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


async def generate_issue(
    db: Database,
    store: BriefingStore,
    windows: BriefingWindowStore,
    attempts: AttemptStore,
    *,
    range_from: Any = None,
    range_to: Any = None,
    sections: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """按窗口/显式范围 + 栏目规则生成一期草稿。

    sections：[{key,label,rule,budget,feedUrl?}]（来自 286 配方或调用方
    内联）。失败 → raise DiagnosisFailure（路由映射 422 + 诊断体）；
    成功 → 新建 draft 期次（provenance='rule'）+ ok attempt。
    """
    missing: list[dict[str, str]] = []
    resolved_from: str
    resolved_to: str
    stage = "candidates"

    if range_from and range_to:
        try:
            resolved_from = _parse_bound(range_from, "from")
            resolved_to = _parse_bound(range_to, "to")
        except BriefingInvalid as exc:
            missing.append({"field": "range", "reason": str(exc)})
            raise await _fail(
                attempts, stage, {}, missing, "显式范围非法。"
            ) from exc
    else:
        window = await windows.get()
        if window is None:
            missing.append(
                {
                    "field": "window",
                    "reason": "未配置截稿窗口（时区 + 截止点），也无法从显式范围生成。",
                }
            )
            raise await _fail(
                attempts, stage, {}, missing, "缺少时间输入：先配置窗口或给出范围。"
            )
        resolved_from = str(window["startUtc"])
        resolved_to = str(window["cutoffUtc"])

    inputs = {
        "from": resolved_from,
        "to": resolved_to,
        "sections": [s.get("key") for s in (sections or [])],
    }

    # stage=candidates：窗口内必须有文章（0 篇 = 缺刊，如实诊断）。
    rows = await db.fetch_all(
        "SELECT entry_ref, item_id, title, feed_title, feed_url, url,"
        " published_at, content_text, starred FROM search_entries"
        " WHERE published_at >= ? AND published_at < ?"
        " ORDER BY published_at DESC, id DESC LIMIT 200",
        (resolved_from, resolved_to),
    )
    if not rows:
        missing.append(
            {
                "field": "entries",
                "reason": f"[{resolved_from}, {resolved_to}) 内没有任何文章。",
            }
        )
        raise await _fail(
            attempts,
            stage,
            inputs,
            missing,
            "窗口内 0 篇文章：先刷新订阅或调整范围，再重新生成。",
        )

    # stage=sections：每个栏目按规则必须筛出文章，缺哪个栏目如实点名。
    stage = "sections"
    section_defs = sections or [
        {"key": "main", "label": "正文", "rule": "recent", "budget": 400}
    ]
    assigned: dict[str, list[dict[str, Any]]] = {}
    used_refs: set[str] = set()
    for definition in section_defs:
        key = str(definition.get("key") or "")
        rule = str(definition.get("rule") or "recent")
        budget = int(definition.get("budget") or 400)
        # 字数预算 → 条数：确定性折算（按摘录均长 100 字符/条），下限 1。
        # 绝不假装精确排版；预算的真实语义是「这个栏目大约值多少字」。
        count_cap = max(1, budget // 100)
        picked: list[dict[str, Any]] = []
        for row in rows:
            if str(row["entry_ref"]) in used_refs:
                continue
            if rule == "starred" and not row["starred"]:
                continue
            if rule == "feed" and str(row["feed_url"]) != str(
                definition.get("feedUrl") or ""
            ):
                continue
            picked.append(dict(row))
            if len(picked) >= count_cap:
                break
        if not picked:
            reason = {
                "starred": "窗口内没有已标星文章（先在阅读时标星，或改规则/范围）。",
                "feed": f"窗口内没有来源 {definition.get('feedUrl')} 的文章。",
                "recent": "窗口内没有文章。",
            }.get(rule, "窗口内没有匹配文章。")
            missing.append({"field": f"section:{key}", "reason": reason})
            continue
        for row in picked:
            used_refs.add(str(row["entry_ref"]))
        assigned[key] = picked
    if missing:
        raise await _fail(
            attempts,
            stage,
            inputs,
            missing,
            "部分栏目按规则筛不出文章（缺刊诊断见 missing），补充后重跑。",
        )

    # stage=assemble：迟到排除在窗口边界天然完成（range_to = cutoffUtc）；
    # 这里兜底防 0 条。
    stage = "assemble"
    if not used_refs:
        missing.append({"field": "items", "reason": "没有可排入的条目。"})
        raise await _fail(attempts, stage, inputs, missing, "装配后 0 条。")

    items: list[dict[str, Any]] = []
    for definition in section_defs:
        key = str(definition.get("key") or "")
        for row in assigned.get(key, []):
            items.append(
                {
                    "entryRef": str(row["entry_ref"]),
                    "itemId": str(row["item_id"]),
                    "title": str(row["title"]),
                    "feedTitle": str(row["feed_title"]),
                    "url": str(row["url"]),
                    "publishedAt": str(row["published_at"]),
                    "excerpt": make_excerpt(str(row["content_text"])),
                    "sectionKey": key,
                    "provenance": "rule",
                }
            )
    issue = await store.create_issue(
        title=f"简报 {resolved_from[:10]}",
        range_from=resolved_from,
        range_to=resolved_to,
        sections=[
            {"key": str(d.get("key")), "label": str(d.get("label") or d.get("key"))}
            for d in section_defs
        ],
        items=items,
        source="generate",
    )
    excluded_late = await db.fetch_one(
        "SELECT COUNT(*) AS n FROM search_entries"
        " WHERE published_at >= ? AND published_at < ?",
        (resolved_to, utc_now()),
    )
    late_count = int(excluded_late["n"]) if excluded_late is not None else 0
    await attempts.record(
        stage="assemble",
        status="ok",
        inputs=inputs,
        missing=[],
        detail=f"生成草稿 {issue['id']}（{len(items)} 条，迟到排除 {late_count} 条）。",
    )
    return {"issue": issue, "excludedLate": late_count, "inputs": inputs}


async def _fail(
    attempts: AttemptStore,
    stage: str,
    inputs: dict[str, Any],
    missing: list[dict[str, str]],
    detail: str,
) -> "DiagnosisFailure":
    record = await attempts.record(
        stage=stage, status="failed", inputs=inputs, missing=missing, detail=detail
    )
    return DiagnosisFailure(stage=stage, missing=missing, detail=detail, attempt=record)


class DiagnosisFailure(Exception):
    """生成失败（映射 422 + 诊断体；诊断已落库）。"""

    def __init__(
        self,
        *,
        stage: str,
        missing: list[dict[str, str]],
        detail: str,
        attempt: dict[str, Any],
    ) -> None:
        super().__init__(detail)
        self.stage = stage
        self.missing = missing
        self.detail = detail
        self.attempt = attempt
