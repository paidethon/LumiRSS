"""NEW-367 搜索会话回溯 —— 保存研究过程的查询序列与选中结果。

语义：
- 一个会话 = 有序查询步（≤50 步，每步 {query, filters, at, refs}）+
  每步用户显式选中的结果（≤100 ref/步，替换式写入）；
- current_step 永远指向最后一步：reopen/detail 返回 resumeStep =
  current_step —— 重新打开即接续到最后一步，绝不回退或重放；
- 步由用户显式追加（记录此刻的查询+过滤意图）；查询序列是事实记录，
  不自动改写历史步骤。

per-user：表在 per-user 库，A 的会话对 B 不可见（列表/详情均如此）。
"""

import json
import uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_SESSIONS = 100
_MAX_STEPS = 50
_MAX_REFS_PER_STEP = 100
_MAX_TITLE = 120
_MAX_QUERY = 200


class SessionNotFound(LookupError):
    """会话不存在（含他人会话——同一 404，不泄露存在性）。"""


class SessionCap(LookupError):
    """超出会话/步骤上限（如实拒绝）。"""


def _steps_of(row: Any) -> list[dict[str, Any]]:
    try:
        steps = json.loads(str(row["steps_json"] or "[]"))
    except ValueError:
        steps = []
    return steps if isinstance(steps, list) else []


def _view(row: Any, *, with_steps: bool = False) -> dict[str, Any]:
    view: dict[str, Any] = {
        "id": str(row["id"]),
        "title": str(row["title"]),
        "currentStep": int(row["current_step"]),
        "stepCount": len(_steps_of(row)),
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
    }
    if with_steps:
        view["steps"] = _steps_of(row)
        view["resumeStep"] = int(row["current_step"])
    return view


async def _get_row(db: Database, session_id: str) -> Any | None:
    await db.migrate()
    return await db.fetch_one(
        "SELECT id, title, steps_json, current_step, created_at, updated_at"
        " FROM search_sessions WHERE id = ?",
        (session_id,),
    )


async def create_session(db: Database, *, title: str) -> dict[str, Any]:
    await db.migrate()
    count_row = await db.fetch_one("SELECT COUNT(*) AS n FROM search_sessions")
    if int(count_row["n"]) >= _MAX_SESSIONS:
        raise SessionCap(
            f"会话数达 {_MAX_SESSIONS} 上限（如实拒绝；请先删除不再需要的会话）。"
        )
    now = utc_now()
    session_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO search_sessions (id, title, steps_json, current_step,"
        " created_at, updated_at) VALUES (?, ?, '[]', -1, ?, ?)",
        (session_id, title.strip()[:_MAX_TITLE], now, now),
    )
    row = await _get_row(db, session_id)
    assert row is not None
    return _view(row)


async def list_sessions(db: Database, *, limit: int = 50) -> dict[str, Any]:
    await db.migrate()
    clean_limit = max(1, min(int(limit), _MAX_SESSIONS))
    rows = await db.fetch_all(
        "SELECT id, title, steps_json, current_step, created_at, updated_at"
        " FROM search_sessions ORDER BY updated_at DESC LIMIT ?",
        (clean_limit,),
    )
    return {"items": [_view(row) for row in rows]}


async def session_detail(db: Database, *, session_id: str) -> dict[str, Any]:
    row = await _get_row(db, session_id)
    if row is None:
        raise SessionNotFound(session_id)
    return _view(row, with_steps=True)


async def append_step(
    db: Database,
    *,
    session_id: str,
    query: str,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """追加一步（用户显式动作）；current_step 指向新步（接续语义）。"""
    row = await _get_row(db, session_id)
    if row is None:
        raise SessionNotFound(session_id)
    steps = _steps_of(row)
    if len(steps) >= _MAX_STEPS:
        raise SessionCap(
            f"会话步数达 {_MAX_STEPS} 上限（如实拒绝；请开新会话继续研究）。"
        )
    steps.append(
        {
            "query": query.strip()[:_MAX_QUERY],
            "filters": filters or {},
            "at": utc_now(),
            "refs": [],
        }
    )
    now = utc_now()
    await db.execute(
        "UPDATE search_sessions SET steps_json = ?, current_step = ?,"
        " updated_at = ? WHERE id = ?",
        (
            json.dumps(steps, ensure_ascii=False, separators=(",", ":")),
            len(steps) - 1,
            now,
            session_id,
        ),
    )
    return await session_detail(db, session_id=session_id)


async def set_step_selections(
    db: Database,
    *,
    session_id: str,
    refs: list[str],
    step: int | None = None,
) -> dict[str, Any]:
    """设置（替换）某步的选中结果；缺省为当前（最后）步。"""
    row = await _get_row(db, session_id)
    if row is None:
        raise SessionNotFound(session_id)
    steps = _steps_of(row)
    if not steps:
        raise SessionCap("会话还没有任何步骤；先记录一步再选择结果。")
    target = int(row["current_step"]) if step is None else int(step)
    if target < 0 or target >= len(steps):
        raise SessionCap("步骤序号越界。")
    clean_refs: list[str] = []
    for ref in refs:
        clean = str(ref).strip()
        if clean and clean not in clean_refs:
            clean_refs.append(clean)
    steps[target]["refs"] = clean_refs[:_MAX_REFS_PER_STEP]
    await db.execute(
        "UPDATE search_sessions SET steps_json = ?, updated_at = ? WHERE id = ?",
        (
            json.dumps(steps, ensure_ascii=False, separators=(",", ":")),
            utc_now(),
            session_id,
        ),
    )
    return await session_detail(db, session_id=session_id)


async def reopen_session(db: Database, *, session_id: str) -> dict[str, Any]:
    """重新打开：接续到最后一步（current_step 即 resume 指针）。"""
    detail = await session_detail(db, session_id=session_id)
    detail["reopened"] = True
    return detail


async def delete_session(db: Database, *, session_id: str) -> bool:
    row = await _get_row(db, session_id)
    if row is None:
        return False
    await db.execute("DELETE FROM search_sessions WHERE id = ?", (session_id,))
    return True
