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
"""

import hmac
import secrets
import time
from typing import Any

from lumirss.storage import Database

_TOKEN_TTL_SECONDS = 30
_SAMPLE_SIZE = 20
_MAX_BACKLOG = 5000
_RESERVED_READ_LATER = "read-later"

_EFFECTIVE_EXCLUSIONS = ["starred", "read-later"]


class BacklogConflict(Exception):
    """token 过期 / 条件漂移（409）。"""


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
