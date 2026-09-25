"""F024 积压整理助手 —— 预览 + 确认执行两段式批量已读。

安全边界：

- 预览返回服务端真实 COUNT（不是样本长度）+ 一次性 token（30s 有效，
  进程内持有——单进程 BFF）；apply 必须携带同一条件 + 该 token，条件
  漂移或过期 → 409，防止「看到的 ≠ 将被改的」；
- starred 与 read-later 由服务端强制排除（参数传 false 也不放开），
  响应回显 effective_exclusions；
- 逐条走既有 set-read 管线（FreshRSS set_entry_state + 投影镜像，
  set 语义）；单条失败收集进 failed[]，不中断整批；
- token 在有效期内可重放：重复 apply 时首批已全部置读，自然收敛为
  applied=0（幂等）。

N049 阅读积压分批处理（本模块扩展）：

- 分批视图（groupBy=source|age）：同一 base 条件下按来源或账龄桶
  分组；每组给 key + 真实 COUNT + 前 100 个 entryRef（诚实有界）；
  age 桶固定（7-30/30-90/90-365/365+ 天），不受 olderThanDays 影响
  ——olderThanDays 只决定候选下限；
- 每批确认走同一两段式 token 流（token condition 携带批次坐标）；
- 每批撤销（undo）以 backlog_batch_log 为界（cap 5，插入时裁最旧）：
  台账记录该批**实际置读成功**的 refs；undo 把这些 ref 恢复 read=0
  （适配器 + 投影镜像，set 语义）；undone 0→1 单向，重复撤销 409。
"""

import hmac
import json
import secrets
import time
import uuid
from datetime import UTC
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_TOKEN_TTL_SECONDS = 30
_SAMPLE_SIZE = 20
_MAX_BACKLOG = 5000
_RESERVED_READ_LATER = "read-later"

_EFFECTIVE_EXCLUSIONS = ["starred", "read-later"]

# N049：分批参数。
_BATCH_GROUP_MODES = ("source", "age")
_BATCH_REFS_LIMIT = 100
_BATCH_APPLY_CAP = 200
_BATCH_LOG_CAP = 5

# N049 age 桶（天）：(lo, hi]，hi=None = 无上界；key 为呈现标签。
_AGE_BUCKETS: tuple[tuple[int, int | None, str], ...] = (
    (7, 30, "7-30天"),
    (30, 90, "30-90天"),
    (90, 365, "90-365天"),
    (365, None, "365天以上"),
)


class BacklogConflict(Exception):
    """token 过期 / 条件漂移（409）。"""


class BatchLogNotFound(Exception):
    """撤销台账不存在（404 backlog_batch_log_not_found）。"""


class BatchAlreadyUndone(Exception):
    """该批已撤销过（409 backlog_batch_already_undone）。"""


# 进程内一次性 token 表：token -> (condition, expires_epoch)
_tokens: dict[str, tuple[dict[str, Any], float]] = {}


def _condition_dict(
    *,
    older_than_days: int,
    feed_url: str | None,
    category_id: str | None,
) -> dict[str, Any]:
    return {
        "olderThanDays": int(older_than_days),
        "feedUrl": feed_url,
        "categoryId": category_id,
    }


def issue_preview_token(condition: dict[str, Any]) -> str:
    token = secrets.token_urlsafe(24)
    # 顺手清理过期 token（表自然有界）。
    now = time.time()
    for key in [k for k, v in _tokens.items() if v[1] < now]:
        _tokens.pop(key, None)
    _tokens[token] = (condition, now + _TOKEN_TTL_SECONDS)
    return token


def validate_apply_token(token: str, condition: dict[str, Any]) -> None:
    entry = _tokens.get(token)
    if entry is None:
        raise BacklogConflict("预览令牌无效或已过期，请重新预览。")
    stored_condition, expires = entry
    if expires < time.time():
        _tokens.pop(token, None)
        raise BacklogConflict("预览令牌已过期（30 秒），请重新预览。")
    if not hmac.compare_digest(
        repr(sorted(stored_condition.items())), repr(sorted(condition.items()))
    ):
        raise BacklogConflict("执行条件与预览条件不一致，已拒绝（防条件漂移）。")


async def backlog_rows(
    db: Database,
    *,
    older_than_days: int,
    feed_url: str | None,
    category_id: str | None,
    limit: int | None,
) -> list[Any]:
    """候选行：未读 + 未加星 + 不在稍后读工作区 + 早于截止时间。

    count = len(rows) 当 limit=None（服务端真实全量计数）。
    """
    cutoff = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - older_than_days * 86400)
    )
    # 参数顺序与 SQL 中占位符出现顺序一致：cutoff → read-later → feed →
    # category → limit。
    params: list[Any] = [cutoff, _RESERVED_READ_LATER]
    where_feed = ""
    if feed_url is not None:
        where_feed = " AND s.feed_url = ?"
        params.append(feed_url)
    where_category = ""
    if category_id is not None:
        where_category = (
            " AND EXISTS (SELECT 1 FROM search_feeds f"
            " WHERE f.category_id = ? AND f.feed_url = s.feed_url)"
        )
        params.append(category_id)
    limit_sql = ""
    if limit is not None:
        limit_sql = " LIMIT ?"
        params.append(limit)
    rows = await db.fetch_all(
        "SELECT s.entry_ref, s.title, s.published_at FROM search_entries s"
        " WHERE s.read = 0 AND s.starred = 0 AND s.published_at < ?"
        " AND NOT EXISTS (SELECT 1 FROM workspace_items w"
        "      WHERE w.workspace_id = ? AND w.item_ref = 'rss:' || s.entry_ref)"
        + where_feed
        + where_category
        + " ORDER BY s.published_at ASC, s.id ASC"
        + limit_sql,
        tuple(params),
    )
    return list(rows)


# ---- N049 阅读积压分批处理 ---------------------------------------------------


def _bucket_bounds(bucket_days: int | None) -> str | None:
    """桶边界天数 → UTC Z 串（``published_at`` 比较用）；None → None。

    published_at >= now-days 表示账龄不足 days 天（更新的不进桶）；
    published_at < now-days 表示账龄已超过 days 天。"""
    if bucket_days is None:
        return None
    from datetime import datetime, timedelta

    moment = datetime.now(UTC) - timedelta(days=bucket_days)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _batch_condition_dict(
    *,
    group_by: str,
    batch_key: str,
    older_than_days: int,
    feed_url: str | None,
    category_id: str | None,
) -> dict[str, Any]:
    return {
        "batch": {"groupBy": group_by, "key": batch_key},
        "olderThanDays": int(older_than_days),
        "feedUrl": feed_url,
        "categoryId": category_id,
    }


async def _batch_where(
    db: Database,
    *,
    group_by: str,
    batch_key: str,
    older_than_days: int,
    feed_url: str | None,
    category_id: str | None,
) -> tuple[str, list[Any]]:
    """批次 WHERE 片段 + 参数（追加在 backlog_rows 同一候选口径之后）。

    source 批：key = feed_url 精确匹配；age 批：key ∈ 固定桶标签，
    published_at 落在 [now-hi, now-lo)。"""
    cutoff = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - older_than_days * 86400)
    )
    base = " AND s.read = 0 AND s.starred = 0 AND s.published_at < ?"
    params: list[Any] = [cutoff]
    if feed_url is not None:
        base += " AND s.feed_url = ?"
        params.append(feed_url)
    if category_id is not None:
        base += " AND EXISTS (SELECT 1 FROM search_feeds f WHERE f.category_id = ? AND f.feed_url = s.feed_url)"
        params.append(category_id)
    base += " AND NOT EXISTS (SELECT 1 FROM workspace_items w WHERE w.workspace_id = ? AND w.item_ref = 'rss:' || s.entry_ref)"
    params.append(_RESERVED_READ_LATER)
    if group_by == "source":
        base += " AND s.feed_url = ?"
        params.append(batch_key)
    elif group_by == "age":
        bucket = next((b for b in _AGE_BUCKETS if b[2] == batch_key), None)
        if bucket is None:
            raise ValueError(f"unknown age bucket: {batch_key}")
        lo, hi, _label = bucket
        # 账龄 ∈ [lo, hi) 天 ⇔ published_at ∈ [now-hi, now-lo)；
        # hi=None（365+ 桶）⇔ published_at < now-lo（无下界）。
        if hi is not None:
            base += " AND s.published_at >= ?"
            params.append(_bucket_bounds(hi))
        base += " AND s.published_at < ?"
        params.append(_bucket_bounds(lo))
    else:
        raise ValueError("group_by must be 'source' or 'age'.")
    return base, params


async def backlog_batch_rows(
    db: Database,
    *,
    group_by: str,
    batch_key: str,
    older_than_days: int,
    feed_url: str | None,
    category_id: str | None,
    limit: int | None,
) -> list[Any]:
    """单批候选行（与 backlog_rows 同一候选口径 + 批次过滤）。"""
    await db.migrate()
    where, params = await _batch_where(
        db,
        group_by=group_by,
        batch_key=batch_key,
        older_than_days=older_than_days,
        feed_url=feed_url,
        category_id=category_id,
    )
    limit_sql = " LIMIT ?" if limit is not None else ""
    if limit is not None:
        params = [*params, limit]
    return list(
        await db.fetch_all(
            "SELECT s.entry_ref, s.title, s.published_at FROM search_entries s"
            " WHERE 1=1" + where + " ORDER BY s.published_at ASC, s.id ASC" + limit_sql,
            tuple(params),
        )
    )


async def backlog_batches(
    db: Database,
    *,
    group_by: str,
    older_than_days: int,
    feed_url: str | None,
    category_id: str | None,
) -> list[dict[str, Any]]:
    """分批视图：[{key, count, entryRefs(≤100)}]；count = 服务端真实
    全量计数（不是样本长度）。

    - source 批：每个有候选的来源一批（key = feed_url）；
    - age 批：四个固定桶各一批（空桶不出现在响应里）。
    """
    if group_by not in _BATCH_GROUP_MODES:
        raise ValueError("group_by must be 'source' or 'age'.")
    rows = await backlog_rows(
        db,
        older_than_days=older_than_days,
        feed_url=feed_url,
        category_id=category_id,
        limit=None,
    )
    if group_by == "source":
        # backlog_rows 出于历史口径不选 feed_url——分组键按候选 ref 集合
        # 单独取（同一投影、同一时点，口径不漂移）。
        refs = [str(row["entry_ref"]) for row in rows]
        feed_map: dict[str, str] = {}
        if refs:
            placeholders = ",".join("?" for _ in refs)
            feed_rows = await db.fetch_all(
                f"SELECT entry_ref, feed_url FROM search_entries WHERE entry_ref IN ({placeholders})",
                tuple(refs),
            )
            feed_map = {
                str(row["entry_ref"]): str(row["feed_url"]) for row in feed_rows
            }
        buckets: dict[str, list[Any]] = {}
        for row in rows:
            buckets.setdefault(
                feed_map.get(str(row["entry_ref"]), ""), []
            ).append(row)
        ordered_keys = sorted(buckets)
        return [
            {
                "key": key,
                "count": len(buckets[key]),
                "entryRefs": [
                    f"rss:{row['entry_ref']}" for row in buckets[key][:_BATCH_REFS_LIMIT]
                ],
            }
            for key in ordered_keys
        ]
    cutoff = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - older_than_days * 86400)
    )
    result: list[dict[str, Any]] = []
    for lo, hi, label in _AGE_BUCKETS:
        hi_bound = _bucket_bounds(hi)
        lo_bound = _bucket_bounds(lo)
        members = [
            row
            for row in rows
            if (hi_bound is None or str(row["published_at"]) >= hi_bound)
            and (lo_bound is None or str(row["published_at"]) < lo_bound)
            and str(row["published_at"]) < cutoff
        ]
        if not members:
            continue
        result.append(
            {
                "key": label,
                "count": len(members),
                "entryRefs": [
                    f"rss:{row['entry_ref']}" for row in members[:_BATCH_REFS_LIMIT]
                ],
            }
        )
    return result


async def record_batch_log(
    db: Database,
    *,
    group_by: str,
    batch_key: str,
    refs: list[str],
    applied_count: int,
) -> str:
    """写入撤销台账（cap 5，插入时裁最旧）；返回台账 id。"""
    await db.migrate()
    log_id = f"bbl-{uuid.uuid4().hex}"
    created_at = utc_now()
    await db.execute(
        "INSERT INTO backlog_batch_log (id, created_at, group_by, batch_key, refs_json, applied_count, undone)"
        " VALUES (?, ?, ?, ?, ?, ?, 0)",
        (
            log_id,
            created_at,
            group_by,
            batch_key,
            json.dumps(refs[:_BATCH_APPLY_CAP], ensure_ascii=False, separators=(",", ":")),
            int(applied_count),
        ),
    )
    await db.execute(
        "DELETE FROM backlog_batch_log WHERE id NOT IN ("
        " SELECT id FROM backlog_batch_log ORDER BY created_at DESC, rowid DESC LIMIT ?)",
        (_BATCH_LOG_CAP,),
    )
    return log_id


def _parse_log_refs(raw: Any) -> list[str]:
    try:
        parsed = json.loads(str(raw or "[]"))
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(ref) for ref in parsed if isinstance(ref, str) and ref]


async def list_batch_logs(db: Database) -> list[dict[str, Any]]:
    """台账列表（新→旧；undone=false 的批次可撤销）。"""
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT id, created_at, group_by, batch_key, refs_json, applied_count, undone"
        " FROM backlog_batch_log ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (_BATCH_LOG_CAP,),
    )
    return [
        {
            "id": str(row["id"]),
            "createdAt": str(row["created_at"]),
            "groupBy": str(row["group_by"]),
            "batchKey": str(row["batch_key"]),
            "refCount": len(_parse_log_refs(row["refs_json"])),
            "appliedCount": int(row["applied_count"]),
            "undone": bool(row["undone"]),
        }
        for row in rows
    ]


async def batch_log_refs_for_undo(db: Database, log_id: str) -> list[str]:
    """取台账 refs 并置 undone=1（已撤销 → BatchAlreadyUndone）。"""
    import sqlite3 as _sqlite3

    from lumirss.db_tx import transaction

    def _tx(conn: _sqlite3.Connection) -> list[str]:
        row = conn.execute(
            "SELECT refs_json, undone FROM backlog_batch_log WHERE id = ?", (log_id,)
        ).fetchone()
        if row is None:
            raise BatchLogNotFound(log_id)
        if int(row["undone"]) == 1:
            raise BatchAlreadyUndone(log_id)
        conn.execute(
            "UPDATE backlog_batch_log SET undone = 1 WHERE id = ?", (log_id,)
        )
        return _parse_log_refs(row["refs_json"])

    return await transaction(db, _tx)
