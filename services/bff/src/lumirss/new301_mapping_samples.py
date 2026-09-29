"""NEW-301 API 字段映射编辑器 —— 用 JSON 样本试映射，预览后绑定。

- 用户粘贴一份 JSON 样本（响应快照），为标题/正文/日期等字段试写
  JMESPath 映射；预览走与生产完全相同的 ``map_items`` 管线（同样的
  编译校验、结果上限与截断）—— 看到的就是绑定的；
- 绑定 = 复用既有 ``ApiSourceStore.update(field_map=…)``：沿用其
  缓存失效语义（etag/last-good 清空、结构基线作废），映射永远落
  在既有 api_sources.field_map，不新增第二份真源；
- 样本按来源归属、受限（每来源 ≤10 份、每份 ≤256KB、label ≤100）；
  样本是用户自己粘进来的数据，随来源删除一并清理（本切片保留：
  来源删除时样本成为孤儿，列表接口按来源取用，不外泄）；
- per-user：api_sources 与样本都在 per-user 库，A 的样本/来源对 B
  完全不可见（B 访问 A 的来源 uuid 得到一致的 404）。
"""

import json
from typing import Any

from lumirss.api_sources import (
    ApiSourceExpressionError,
    ApiSourceInvalid,
    map_items,
    validate_field_map,
    validate_items_expr,
)
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_SAMPLES_PER_SOURCE = 10
MAX_SAMPLE_BYTES = 256 * 1024
MAX_LABEL_LENGTH = 100
_PREVIEW_ITEM_LIMIT = 5


class SampleInvalid(ValueError):
    """样本负载非法（映射 422）。"""


def clean_label(label: Any) -> str:
    if not isinstance(label, str) or not label.strip():
        raise SampleInvalid("label 不能为空。")
    clean = label.strip()
    if len(clean) > MAX_LABEL_LENGTH:
        raise SampleInvalid(f"label 最长 {MAX_LABEL_LENGTH} 字符。")
    return clean


def clean_sample_json(raw: Any) -> str:
    """样本必须是合法 JSON 且体积受限；规范化存储（紧凑序列化）。"""
    if isinstance(raw, (dict, list)):
        text = json.dumps(raw, ensure_ascii=False)
    elif isinstance(raw, str):
        text = raw
    else:
        raise SampleInvalid("sampleJson 必须是 JSON 对象/数组或 JSON 文本。")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SampleInvalid(f"sampleJson 不是合法 JSON：{exc}") from exc
    canonical = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(canonical.encode("utf-8")) > MAX_SAMPLE_BYTES:
        raise SampleInvalid(f"样本超过 {MAX_SAMPLE_BYTES // 1024}KB 上限。")
    return canonical


def preview_sample_mapping(
    sample_json: str | dict | list,
    field_map: dict[str, str],
    items_expr: str = "[*]",
) -> dict[str, Any]:
    """用试写的映射跑生产 map_items 管线（≤5 条预览 + 总数）。

    ``sample_json`` 接受 JSON 文本或已解析的 dict/list（存储返回形状）。
    表达式非法 → SampleInvalid（422）；求值失败 → 同样 422（错误类型
    区分）。零写入 —— 预览不改任何配置。"""
    try:
        clean_map = validate_field_map(field_map)
    except (ApiSourceInvalid, ApiSourceExpressionError) as exc:
        raise SampleInvalid(f"映射不合法：{exc}") from exc
    try:
        clean_items = validate_items_expr(items_expr) if items_expr.strip() else "[*]"
    except (ApiSourceInvalid, ApiSourceExpressionError) as exc:
        raise SampleInvalid(f"items 表达式不合法：{exc}") from exc
    try:
        payload = (
            json.loads(sample_json)
            if isinstance(sample_json, str)
            else sample_json
        )
    except json.JSONDecodeError as exc:
        raise SampleInvalid(f"样本不是合法 JSON：{exc}") from exc
    try:
        items = map_items(payload, clean_items, clean_map)
    except ApiSourceExpressionError as exc:
        raise SampleInvalid(f"映射表达式无法用于该样本：{exc}") from exc
    return {
        "items": [{key: item.get(key) for key in item} for item in items[:_PREVIEW_ITEM_LIMIT]],
        "totalAvailable": len(items),
    }


class MappingSampleStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def save_sample(self, source_uuid: str, label: str, sample_json: Any) -> dict[str, Any]:
        clean = clean_label(label)
        payload = clean_sample_json(sample_json)
        await self._db.migrate()
        count_row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM api_mapping_samples WHERE source_uuid = ?",
            (source_uuid,),
        )
        if count_row is not None and int(count_row["n"]) >= MAX_SAMPLES_PER_SOURCE:
            raise SampleInvalid(f"每来源最多 {MAX_SAMPLES_PER_SOURCE} 份样本，请先删除旧的。")
        cursor = await self._db.execute(
            "INSERT INTO api_mapping_samples (source_uuid, label, sample_json, created_at) VALUES (?, ?, ?, ?)",
            (source_uuid, clean, payload, utc_now()),
        )
        return {
            "id": int(cursor),
            "sourceUuid": source_uuid,
            "label": clean,
            "sampleJson": json.loads(payload),
            "createdAt": utc_now(),
        }

    async def get_sample(self, source_uuid: str, sample_id: int) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, source_uuid, label, sample_json, created_at FROM api_mapping_samples "
            "WHERE id = ? AND source_uuid = ?",
            (sample_id, source_uuid),
        )
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "sourceUuid": str(row["source_uuid"]),
            "label": str(row["label"]),
            "sampleJson": json.loads(str(row["sample_json"])),
            "createdAt": str(row["created_at"]),
        }

    async def list_samples(self, source_uuid: str) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, source_uuid, label, sample_json, created_at FROM api_mapping_samples "
            "WHERE source_uuid = ? ORDER BY id DESC",
            (source_uuid,),
        )
        return [
            {
                "id": int(row["id"]),
                "sourceUuid": str(row["source_uuid"]),
                "label": str(row["label"]),
                "sampleJson": json.loads(str(row["sample_json"])),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]

    async def delete_sample(self, source_uuid: str, sample_id: int) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM api_mapping_samples WHERE id = ? AND source_uuid = ?",
            (sample_id, source_uuid),
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM api_mapping_samples WHERE id = ?", (sample_id,)
        )
        return True


_ = (ApiSourceInvalid,)
