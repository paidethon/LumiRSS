"""NEW-398 错误自助处理单 —— 经验证的用户侧步骤 + 逐步效果 + 脱敏求助。

边界（硬规则）：

- 处理单步骤是模块内**人工复核过的注册表**（随代码发布，不落库）：
  每个错误码的步骤只描述用户侧可执行、且与真实界面/配置对应的事情
  （管理台系统面板、环境变量、来源页手动刷新）；不提供 shell、日志
  直读或任何越权操作；
- 逐步记录效果：用户对每一步显式记录 tried/helped/no_effect/skipped
  （每步至多一条，重复记录 = 覆盖），这是「记录」不是「推断」；
- 升级生成的求助材料只含：错误码 + 各步骤结果 + 用户自填备注 +
  构建版本——不含用户标识、数据库路径、会话标识、正文或凭据。
"""

import json
from typing import Any

from lumirss.config import LumiSettings
from lumirss.storage import Database
from lumirss.util import utc_now

OUTCOMES = ("tried", "helped", "no_effect", "skipped")
_MAX_NOTE = 500

# 注册表：code 与 errors.py 稳定错误类型一一对应（真实存在的错误码）。
RUNBOOKS: dict[str, dict[str, Any]] = {
    "connection_error": {
        "title": "无法连接 FreshRSS（connection_error）",
        "verified": "对应 UpstreamConnectionError(502) 的用户侧处置；界面入口与配置键均来自当前实现。",
        "steps": [
            {
                "index": 1,
                "title": "打开管理台系统面板确认服务检测",
                "detail": "管理员界面 → 系统面板查看 FreshRSS 配置检测与最近检测时间（NEW-397 状态页）。",
            },
            {
                "index": 2,
                "title": "核对 FRESHRSS_BASE_URL / FRESHRSS_USERNAME / FRESHRSS_API_PASSWORD",
                "detail": "三个环境变量必须同时配置；URL 必须是 BFF 容器可达的 FreshRSS 地址。",
            },
            {
                "index": 3,
                "title": "在来源页对单个来源手动刷新验证",
                "detail": "配置修正后重启 BFF，在来源管理页对一个来源执行手动刷新，确认恢复。",
            },
        ],
    },
    "ai_not_configured": {
        "title": "AI 未配置（ai_not_configured）",
        "verified": "对应 AiNotConfigured(503) 的用户侧处置。",
        "steps": [
            {
                "index": 1,
                "title": "管理员在设置中配置 AI_API_KEY",
                "detail": "OpenAI 兼容 API Key 仅存服务端；设置后无需重启即可在摘要功能中重试。",
            },
            {
                "index": 2,
                "title": "重试一次摘要/翻译操作",
                "detail": "仍失败时新建处理单升级为求助材料，附上各步骤结果。",
            },
        ],
    },
    "rsshub_not_configured": {
        "title": "RSSHub 未配置（rsshub_not_configured）",
        "verified": "对应 RssHubNotConfigured(503) 的用户侧处置。",
        "steps": [
            {
                "index": 1,
                "title": "配置 RSSHUB_BASE_URL",
                "detail": "指向你的 RSSHub 实例；订阅路由 URL 由该基地址构建。",
            },
            {
                "index": 2,
                "title": "在添加来源页用路由预览验证",
                "detail": "选择 RSSHub 路由并预览，确认能取到条目再订阅。",
            },
        ],
    },
}


class RunbookUnknown(LookupError):
    """错误码不在注册表里（404 同形）。"""


class SessionNotFound(Exception):
    """处理单不存在或不属于调用者（404 同形）。"""


class StepInvalid(ValueError):
    """步骤记录非法（422）。"""


def _clean(value: Any, limit: int, *, required: bool = False, field: str) -> str:
    if value is None:
        if required:
            raise StepInvalid(f"{field} 不能为空。")
        return ""
    if not isinstance(value, str):
        raise StepInvalid(f"{field} 必须是字符串。")
    clean = value.strip()
    if required and not clean:
        raise StepInvalid(f"{field} 不能为空。")
    if len(clean) > limit:
        raise StepInvalid(f"{field} 最长 {limit} 字符。")
    return clean


def list_runbooks() -> dict[str, Any]:
    return {
        "runbooks": [
            {
                "code": code,
                "title": spec["title"],
                "verified": spec["verified"],
                "steps": [dict(step) for step in spec["steps"]],
            }
            for code, spec in RUNBOOKS.items()
        ]
    }


async def open_session(db: Database, user_id: str, *, code: str) -> dict[str, Any]:
    spec = RUNBOOKS.get(code)
    if spec is None:
        raise RunbookUnknown("该错误码没有处理单。")
    await db.migrate()
    now = utc_now()
    new_id = await db.execute(
        "INSERT INTO error_runbook_sessions (user_id, code, status, created_at,"
        " updated_at) VALUES (?, ?, 'open', ?, ?)",
        (user_id, code, now, now),
    )
    return {
        "id": str(new_id),
        "code": code,
        "title": spec["title"],
        "status": "open",
        "createdAt": now,
        "steps": [dict(step) for step in spec["steps"]],
        "outcomes": [],
    }


async def _owned_session(db: Database, user_id: str, session_id: str) -> Any:
    try:
        numeric = int(str(session_id))
    except ValueError as exc:
        raise SessionNotFound("没有这张处理单。") from exc
    row = await db.fetch_one(
        "SELECT * FROM error_runbook_sessions WHERE id = ? AND user_id = ?",
        (numeric, user_id),
    )
    if row is None:
        raise SessionNotFound("没有这张处理单。")
    return row


async def record_step(
    db: Database,
    user_id: str,
    *,
    session_id: str,
    step_index: Any,
    outcome: str,
    note: str = "",
) -> dict[str, Any]:
    spec = None
    session = await _owned_session(db, user_id, session_id)
    spec = RUNBOOKS.get(str(session["code"]))
    if spec is None:
        raise RunbookUnknown("该错误码没有处理单。")
    try:
        index = int(step_index)
    except (TypeError, ValueError) as exc:
        raise StepInvalid("stepIndex 必须是整数。") from exc
    known = {int(step["index"]) for step in spec["steps"]}
    if index not in known:
        raise StepInvalid("stepIndex 不在该处理单的步骤里。")
    if outcome not in OUTCOMES:
        raise StepInvalid("outcome 必须是 tried/helped/no_effect/skipped。")
    clean_note = _clean(note, _MAX_NOTE, field="备注")
    now = utc_now()
    existing = await db.fetch_one(
        "SELECT id FROM error_runbook_steps WHERE session_id = ? AND step_index = ?",
        (int(session["id"]), index),
    )
    if existing is None:
        await db.execute(
            "INSERT INTO error_runbook_steps (session_id, step_index, outcome,"
            " note, recorded_at) VALUES (?, ?, ?, ?, ?)",
            (int(session["id"]), index, outcome, clean_note, now),
        )
    else:
        await db.execute(
            "UPDATE error_runbook_steps SET outcome = ?, note = ?, recorded_at = ?"
            " WHERE id = ?",
            (outcome, clean_note, now, existing["id"]),
        )
    await db.execute(
        "UPDATE error_runbook_sessions SET updated_at = ? WHERE id = ?",
        (now, int(session["id"])),
    )
    return {"sessionId": str(session["id"]), "stepIndex": index,
            "outcome": outcome, "recordedAt": now}


async def get_session(db: Database, user_id: str, session_id: str) -> dict[str, Any]:
    session = await _owned_session(db, user_id, session_id)
    spec = RUNBOOKS.get(str(session["code"]))
    steps = await db.fetch_all(
        "SELECT * FROM error_runbook_steps WHERE session_id = ? ORDER BY step_index",
        (int(session["id"]),),
    )
    material = None
    if session["material_json"]:
        try:
            material = json.loads(str(session["material_json"]))
        except ValueError:
            material = None
    return {
        "id": str(session["id"]),
        "code": str(session["code"]),
        "title": spec["title"] if spec else str(session["code"]),
        "status": str(session["status"]),
        "createdAt": str(session["created_at"]),
        "updatedAt": str(session["updated_at"]),
        "steps": [dict(step) for step in (spec["steps"] if spec else [])],
        "outcomes": [
            {
                "stepIndex": int(row["step_index"]),
                "outcome": str(row["outcome"]),
                "note": str(row["note"]),
                "recordedAt": str(row["recorded_at"]),
            }
            for row in steps
        ],
        "escalatedNote": str(session["escalated_note"]),
        "material": material,
    }


async def list_sessions(db: Database, user_id: str) -> dict[str, Any]:
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT id, code, status, created_at, updated_at FROM"
        " error_runbook_sessions WHERE user_id = ? ORDER BY created_at DESC, id DESC",
        (user_id,),
    )
    return {
        "sessions": [
            {
                "id": str(row["id"]),
                "code": str(row["code"]),
                "status": str(row["status"]),
                "createdAt": str(row["created_at"]),
                "updatedAt": str(row["updated_at"]),
            }
            for row in rows
        ]
    }


async def resolve_session(
    db: Database, user_id: str, session_id: str
) -> dict[str, Any]:
    session = await _owned_session(db, user_id, session_id)
    now = utc_now()
    await db.execute(
        "UPDATE error_runbook_sessions SET status = 'resolved', updated_at = ?"
        " WHERE id = ?",
        (now, int(session["id"])),
    )
    return {"id": str(session["id"]), "status": "resolved", "updatedAt": now}


async def escalate_session(
    db: Database, user_id: str, session_id: str, *, note: str
) -> dict[str, Any]:
    session = await _owned_session(db, user_id, session_id)
    clean_note = _clean(note, _MAX_NOTE, required=True, field="求助备注")
    detail = await get_session(db, user_id, session_id)
    # 脱敏材料：错误码 + 步骤结果 + 用户备注 + 构建版本。没有其他任何东西。
    material = {
        "code": detail["code"],
        "version": LumiSettings().LUMIRSS_VERSION,
        "steps": [
            {
                "stepIndex": outcome["stepIndex"],
                "outcome": outcome["outcome"],
            }
            for outcome in detail["outcomes"]
        ],
        "userNote": clean_note,
        "generatedAt": utc_now(),
    }
    now = utc_now()
    await db.execute(
        "UPDATE error_runbook_sessions SET status = 'escalated', escalated_note = ?,"
        " material_json = ?, updated_at = ? WHERE id = ?",
        (clean_note, json.dumps(material, ensure_ascii=False), now, int(session["id"])),
    )
    return {"id": str(session["id"]), "status": "escalated", "material": material}
