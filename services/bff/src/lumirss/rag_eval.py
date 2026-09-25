"""N159 检索质量收藏 —— 私有 RAG 评测样例（保存时捕获真实命中）。

- 保存（save_sample）：服务端【立即】用当前索引执行一次真实检索并
  把实际命中（actualRefs，去重有界 50）与期望命中（expectedRefs）、
  过滤条件（kind）一起存进本用户库——评测样例是「查询 + 当时结果」
  的快照，不是裸期望；
- 重放（rerun_sample）：现在再跑同一查询，与存档做双向差分：
  * ``hitExpected``  = 期望命中 ∩ 现在实际命中（期望里仍然找得到的）；
  * ``missed``       = 期望命中 − 现在实际命中（期望里现在找不到的）；
  * ``newHits``      = 现在实际命中 − 存档实际命中（索引变化带来的
    新命中——漂移信号）；
  * storedActualRefs / nowActualRefs 原样回显，绝不只给结论不给证据；
- 私有边界：表在每用户库（per-user DB），他人结构上不可见；绝不进入
  任何导出/分享包，也不属于备份范围组件（backup_scope 组件→表映射
  刻意不含本表——评测样例是本地工作台数据，文档化为 local-only）；
- 上限 50 条：满了 409 eval_sample_limit（诚实拒绝，绝不静默挤出
  最旧行——评测基线被无声替换比拒绝更危险）。

本文件直接写站点 2 处（样例 INSERT / DELETE）。
"""

import json
import uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_CAP = 50
_MAX_REFS = 50
_MAX_QUERY_LENGTH = 500
_SEARCH_K = 20


class EvalSampleInvalid(ValueError):
    """样例载荷非法（查询长度/引用数量），映射 422。"""


class EvalSampleLimit(Exception):
    """样例数已达上限（50），映射 409。"""


class EvalSampleNotFound(Exception):
    """样例不存在（或不属于本用户库），映射 404。"""


def _decode_refs(raw: Any) -> list[str]:
    try:
        parsed = json.loads(str(raw or "[]"))
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(ref) for ref in parsed if isinstance(ref, str)]


def _decode_kind(raw: Any) -> str | None:
    if not raw:
        return None
    try:
        parsed = json.loads(str(raw))
    except ValueError:
        return None
    return str(parsed) if isinstance(parsed, str) and parsed else None


class RagEvalSampleStore:
    """Persistence + search orchestration for rag_eval_samples (N159)."""

    def __init__(self, db: Database, rag_service: Any) -> None:
        self._db = db
        self._rag = rag_service

    async def save(
        self, *, query: str, expected_refs: list[str], kind: str | None = None
    ) -> dict[str, Any]:
        clean_query = _validate_query(query)
        expected = _validate_refs(expected_refs)
        clean_kind = _validate_kind(kind)
        await self._db.migrate()
        count_row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM rag_eval_samples"
        )
        if count_row is not None and int(count_row["n"]) >= _CAP:
            raise EvalSampleLimit(f"评测样例已达上限（{_CAP}）。")
        actual = await self._search_now(clean_query, clean_kind)
        sample_id = f"eval-{uuid.uuid4().hex}"
        created_at = utc_now()
        await self._db.execute(
            "INSERT INTO rag_eval_samples (id, query, expected_refs_json, actual_refs_json, scope_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                sample_id,
                clean_query,
                json.dumps(expected, ensure_ascii=False),
                json.dumps(actual, ensure_ascii=False),
                json.dumps(clean_kind) if clean_kind else None,
                created_at,
            ),
        )
        sample = await self.get(sample_id)
        assert sample is not None
        return sample

    async def list_samples(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, query, expected_refs_json, actual_refs_json, scope_json, created_at FROM rag_eval_samples ORDER BY created_at DESC, id DESC"
        )
        return [self._view(row) for row in rows]

    async def get(self, sample_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, query, expected_refs_json, actual_refs_json, scope_json, created_at FROM rag_eval_samples WHERE id = ?",
            (sample_id,),
        )
        return self._view(row) if row is not None else None

    async def delete(self, sample_id: str) -> bool:
        await self._db.migrate()

        def _tx(conn: Any) -> bool:
            cursor = conn.execute(
                "DELETE FROM rag_eval_samples WHERE id = ?", (sample_id,)
            )
            return cursor.rowcount > 0

        from lumirss.db_tx import transaction

        return bool(await transaction(self._db, _tx))

    async def rerun(self, sample_id: str) -> dict[str, Any]:
        """重放查询并差分（语义见模块注释）。样例不存在 → 404。"""
        sample = await self.get(sample_id)
        if sample is None:
            raise EvalSampleNotFound(sample_id)
        now_actual = await self._search_now(
            str(sample["query"]), sample["kind"]
        )
        stored_actual = list(sample["actualRefs"])
        expected = list(sample["expectedRefs"])
        now_set = set(now_actual)
        stored_set = set(stored_actual)
        return {
            "sampleId": sample_id,
            "query": str(sample["query"]),
            "storedActualRefs": stored_actual,
            "nowActualRefs": now_actual,
            "hitExpected": [ref for ref in expected if ref in now_set],
            "missed": [ref for ref in expected if ref not in now_set],
            "newHits": [ref for ref in now_actual if ref not in stored_set],
            "ranAt": utc_now(),
        }

    async def _search_now(self, query: str, kind: str | None) -> list[str]:
        result = await self._rag.search(
            query, k=_SEARCH_K, kind=kind if kind else None
        )
        refs: list[str] = []
        for item in result.get("items", []):
            ref = str(item.get("ref") or "")
            if ref and ref not in refs:
                refs.append(ref)
        return refs[:_MAX_REFS]

    @staticmethod
    def _view(row: Any) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "query": str(row["query"]),
            "expectedRefs": _decode_refs(row["expected_refs_json"]),
            "actualRefs": _decode_refs(row["actual_refs_json"]),
            "kind": _decode_kind(row["scope_json"]),
            "createdAt": str(row["created_at"]),
        }


def _validate_query(query: str) -> str:
    if not isinstance(query, str):
        raise EvalSampleInvalid("query 必须是字符串。")
    clean = query.strip()
    if not clean:
        raise EvalSampleInvalid("query 不能为空。")
    if len(clean) > _MAX_QUERY_LENGTH:
        raise EvalSampleInvalid(f"query 过长（max {_MAX_QUERY_LENGTH} 字符）。")
    return clean


def _validate_refs(refs: list[str]) -> list[str]:
    if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
        raise EvalSampleInvalid("expectedRefs 必须是字符串数组。")
    cleaned: list[str] = []
    for ref in refs:
        text = ref.strip()
        if text and text not in cleaned:
            cleaned.append(text)
    if len(cleaned) > _MAX_REFS:
        raise EvalSampleInvalid(f"expectedRefs 最多 {_MAX_REFS} 个。")
    return cleaned


def _validate_kind(kind: str | None) -> str | None:
    if kind is None:
        return None
    clean = str(kind).strip()
    return clean or None
