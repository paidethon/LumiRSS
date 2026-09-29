"""NEW-246 资料来源链 —— 手工登记引用边的链条追踪。

语义边界（模块存在的理由）：

- citation_edges 只有用户手动登记的「A 引用了 B」一条边；系统绝不
  推断：链条查询只沿显式登记的出边走，不查 FreshRSS、不查全文、
  不猜相似标题；
- 链条节点状态：
  * has_outgoing_edges=true → 继续下钻（用户登记过它的出处）；
  * false → 「中间环节缺失」：被引目标没有登记它自己引用了什么。
    这是诚实缺项（用户没登记 ≠ 它没有出处），不猜测、不补位；
- 同一对 (from, to) 至多一条边（应用层查重 → 409）；自环 422；
- 环检测：追踪途中回到已访问节点 → 环如实报告（cycle=true）并停；
  深度上限 20（有界，防超长链）。

per-user 库：边天然按账户隔离。
"""

import sqlite3
import uuid as _uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_DEPTH = 20
_NOTE_MAX = 500
_REF_MAX = 300


class ChainInvalid(ValueError):
    """边负载非法（映射 422）。"""


class ChainConflict(Exception):
    """同一对引用边已登记（映射 409）。"""


class EdgeNotFound(Exception):
    """边不存在（映射 404）。"""


def _clean_ref(value: Any, field: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= _REF_MAX:
        raise ChainInvalid(f"{field} 必须是 1-{_REF_MAX} 个字符。")
    return value.strip()


class CitationChainStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- 边登记 --------------------------------------------------------------

    async def add_edge(self, from_ref: str, to_ref: str, note: str) -> dict[str, Any]:
        clean_from = _clean_ref(from_ref, "fromRef")
        clean_to = _clean_ref(to_ref, "toRef")
        if clean_from == clean_to:
            raise ChainInvalid("自引用边没有信息量（fromRef = toRef）。")
        if not isinstance(note, str) or len(note.strip()) > _NOTE_MAX:
            raise ChainInvalid(f"note 最多 {_NOTE_MAX} 个字符。")
        clean_note = note.strip()
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            existing = conn.execute(
                "SELECT id FROM citation_edges WHERE from_ref = ? AND to_ref = ?",
                (clean_from, clean_to),
            ).fetchone()
            if existing is not None:
                raise ChainConflict(str(existing["id"]))
            conn.execute(
                "INSERT INTO citation_edges (id, from_ref, to_ref, note, registered_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(_uuid.uuid4()), clean_from, clean_to, clean_note, now),
            )

        await transaction(self._db, _tx)
        return {"fromRef": clean_from, "toRef": clean_to, "note": clean_note, "registeredAt": now}

    async def list_edges(self, *, from_ref: str | None = None) -> list[dict[str, Any]]:
        await self._db.migrate()
        if from_ref is not None:
            rows = await self._db.fetch_all(
                "SELECT id, from_ref, to_ref, note, registered_at FROM citation_edges "
                "WHERE from_ref = ? ORDER BY registered_at DESC, rowid DESC",
                (from_ref,),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT id, from_ref, to_ref, note, registered_at FROM citation_edges "
                "ORDER BY registered_at DESC, rowid DESC LIMIT 200",
                (),
            )
        return [
            {
                "id": str(row["id"]),
                "fromRef": str(row["from_ref"]),
                "toRef": str(row["to_ref"]),
                "note": str(row["note"]),
                "registeredAt": str(row["registered_at"]),
            }
            for row in rows
        ]

    async def delete_edge(self, edge_id: str) -> None:
        await self._db.migrate()

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM citation_edges WHERE id = ?", (edge_id,))

        await transaction(self._db, _tx)

    # -- 链条追踪 --------------------------------------------------------------

    async def trace_chain(self, start_ref: str) -> dict[str, Any]:
        """沿显式出边走：本篇引用了什么 → 它又引用了什么……
        出边缺失 = 中间环节缺失（诚实标注，不推断）。"""
        clean_start = _clean_ref(start_ref, "ref")
        await self._db.migrate()
        chain: list[dict[str, Any]] = []
        visited = {clean_start}
        current = clean_start
        cycle = False
        truncated = False

        while True:
            rows = await self._db.fetch_all(
                "SELECT id, to_ref, note, registered_at FROM citation_edges "
                "WHERE from_ref = ? ORDER BY registered_at ASC, rowid ASC",
                (current,),
            )
            if not rows:
                # 当前节点没有登记出处：链条尽头（起点本身=没有登记引用关系）
                chain.append(
                    {
                        "ref": current,
                        "missingLink": current != clean_start,
                        "edges": [],
                    }
                )
                break
            edges = [
                {
                    "id": str(row["id"]),
                    "toRef": str(row["to_ref"]),
                    "note": str(row["note"]),
                    "registeredAt": str(row["registered_at"]),
                }
                for row in rows
            ]
            chain.append({"ref": current, "missingLink": False, "edges": edges})
            # 单出边才继续下钻；多出边 = 分叉（全部列出，不选边猜主链）
            next_edges = [e for e in edges if e["toRef"] in visited]
            if next_edges:
                cycle = True
                break
            if len(edges) == 1:
                current = edges[0]["toRef"]
                visited.add(current)
                if len(chain) >= _MAX_DEPTH:
                    truncated = True
                    break
                continue
            # 多出边：为每个分支标注「有登记」，但不再下钻（避免组合爆炸）
            break

        return {
            "startRef": clean_start,
            "chain": chain,
            "cycle": cycle,
            "truncated": truncated,
            "depthLimit": _MAX_DEPTH,
        }
