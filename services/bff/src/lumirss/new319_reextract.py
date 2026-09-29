"""NEW-319 资料重新提取请求 —— 对已存网页发起一次新提取，旧版保持可读。

- 请求（POST reextract）：落 pending 行 → 同请求内执行一次有界抓取
  （继承 clip_fetch 的 SSRF 预检 + pinned dial + 5MB/30s 上限，可注入
  mock）→ done（保存净化后的新正文）/ failed（如实带原因）；同步完成
  = 没有后台任务黑洞，结果立即可见；
- 旧版保持可读：done 不改动 library_clips 任何列；``apply`` 是唯一
  写入点，且只写 F089 修订槽（revised_content_html），原始版本经
  GET /full 保持可读，笔记/批注锚点一字不动；apply 幂等（applied
  台账防重复应用同一版本 —— 已应用 → 409 applied_already）；
- 请求上限 50 行/剪藏域（超限裁最老，与既有 cap 模式一致）；
  不可达 → failed 行 + 路由 502 双通道诚实。

per-user：请求行与剪藏同库（RoutingDatabase），A 的请求对 B 不可见。
"""

import uuid as _uuid
from typing import Any

from lumirss.clip_fetch import fetch_extract_sanitize
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_REQUESTS = 50


class ReextractTargetNotFound(Exception):
    """目标剪藏不存在（404）。"""


class ReextractNotFound(Exception):
    """请求行不存在（404）。"""


class ReextractAlreadyApplied(Exception):
    """该版本已应用过（409）。"""


class ReextractNotApplicable(Exception):
    """只有 done 状态的请求可以应用（409）。"""


class ReextractService:
    """重提取请求（fetcher 可注入；默认真实有界管线）。"""

    def __init__(self, db: Database, *, fetcher: Any = None) -> None:
        self._db = db
        self._fetcher = fetcher or fetch_extract_sanitize

    async def request(self, clip_item_uuid: str) -> dict[str, Any]:
        clip = await self._clip(clip_item_uuid)
        if clip is None:
            raise ReextractTargetNotFound()
        await self._db.migrate()
        request_id = str(_uuid.uuid4())
        now = utc_now()
        await self._prune_past_cap(clip_item_uuid)
        await self._db.execute(
            "INSERT INTO clip_reextractions (id, clip_item_uuid, status, requested_at)"
            " VALUES (?, ?, 'pending', ?)",
            (request_id, clip_item_uuid, now),
        )
        try:
            page = await self._fetcher(str(clip["url"]))
        except Exception as exc:  # 网络层失败 → failed 行，如实带原因
            await self._db.execute(
                "UPDATE clip_reextractions SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
                (str(exc)[:500], utc_now(), request_id),
            )
            result = await self.get_request(clip_item_uuid, request_id)
            assert result is not None
            return result
        title = (page.title or "")[:500]
        await self._db.execute(
            "UPDATE clip_reextractions SET status = 'done', title = ?, content_html = ?, content_text = ?, finished_at = ? WHERE id = ?",
            (title, page.content_html, page.content_text, utc_now(), request_id),
        )
        result = await self.get_request(clip_item_uuid, request_id)
        assert result is not None
        return result

    async def list_requests(self, clip_item_uuid: str) -> dict[str, Any]:
        if await self._clip(clip_item_uuid) is None:
            raise ReextractTargetNotFound()
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT r.id, r.status, r.title, r.content_text, r.error, r.requested_at, r.finished_at,"
            " EXISTS(SELECT 1 FROM clip_reextractions_applied a WHERE a.reextraction_id = r.id) AS applied"
            " FROM clip_reextractions r WHERE r.clip_item_uuid = ?"
            " ORDER BY r.requested_at DESC, r.id DESC LIMIT 50",
            (clip_item_uuid,),
        )
        return {
            "clipRef": f"library:{clip_item_uuid}",
            "requests": [
                {
                    "id": str(row["id"]),
                    "status": str(row["status"]),
                    "title": str(row["title"]),
                    "charCount": len(str(row["content_text"])),
                    "preview": str(row["content_text"])[:200],
                    "error": str(row["error"]) or None,
                    "applied": bool(row["applied"]),
                    "requestedAt": str(row["requested_at"]),
                    "finishedAt": (
                        str(row["finished_at"]) if row["finished_at"] else None
                    ),
                }
                for row in rows
            ],
        }

    async def get_request(
        self, clip_item_uuid: str, request_id: str
    ) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, status, title, content_text, error, requested_at, finished_at"
            " FROM clip_reextractions WHERE id = ? AND clip_item_uuid = ?",
            (request_id, clip_item_uuid),
        )
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "clipRef": f"library:{clip_item_uuid}",
            "status": str(row["status"]),
            "title": str(row["title"]),
            "charCount": len(str(row["content_text"])),
            "preview": str(row["content_text"])[:200],
            "error": str(row["error"]) or None,
            "requestedAt": str(row["requested_at"]),
            "finishedAt": str(row["finished_at"]) if row["finished_at"] else None,
        }

    async def apply(self, clip_item_uuid: str, request_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT status, content_html FROM clip_reextractions"
            " WHERE id = ? AND clip_item_uuid = ?",
            (request_id, clip_item_uuid),
        )
        if row is None:
            raise ReextractNotFound()
        if str(row["status"]) != "done":
            raise ReextractNotApplicable()
        already = await self._db.fetch_one(
            "SELECT 1 AS ok FROM clip_reextractions_applied WHERE reextraction_id = ?",
            (request_id,),
        )
        if already is not None:
            raise ReextractAlreadyApplied()
        if await self._clip(clip_item_uuid) is None:
            raise ReextractTargetNotFound()
        now = utc_now()

        def _tx(conn: Any) -> None:
            conn.execute(
                "UPDATE library_clips SET revised_content_html = ?, revised_at = ? WHERE item_uuid = ?",
                (str(row["content_html"]), now, clip_item_uuid),
            )
            conn.execute(
                "INSERT INTO clip_reextractions_applied (reextraction_id, applied_at) VALUES (?, ?)",
                (request_id, now),
            )

        from lumirss.db_tx import transaction

        await transaction(self._db, _tx)
        return {
            "id": request_id,
            "clipRef": f"library:{clip_item_uuid}",
            "appliedAt": now,
            "note": "新版本已切到展示位（修订槽）；原始版本保持可读，笔记锚点未改动。",
        }

    async def _prune_past_cap(self, clip_item_uuid: str) -> None:
        rows = await self._db.fetch_all(
            "SELECT id FROM clip_reextractions WHERE clip_item_uuid = ?"
            " ORDER BY requested_at ASC, id ASC",
            (clip_item_uuid,),
        )
        excess = len(rows) + 1 - _MAX_REQUESTS
        for index in range(max(0, excess)):
            await self._db.execute(
                "DELETE FROM clip_reextractions WHERE id = ?",
                (str(rows[index]["id"]),),
            )

    async def _clip(self, clip_item_uuid: str) -> Any:
        await self._db.migrate()
        return await self._db.fetch_one(
            "SELECT item_uuid, url FROM library_clips WHERE item_uuid = ?",
            (clip_item_uuid,),
        )
