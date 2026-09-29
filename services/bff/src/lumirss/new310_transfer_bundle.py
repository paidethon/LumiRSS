"""NEW-310 接入配置转移包 —— 导出不含秘密的配置，导入时重选凭据。

- 导出：API 来源的名称/端点/items 表达式/字段映射/分页/调度预算，
  附稳定 ``credentialRef``（= 原实例来源 uuid 的不透明引用）；绝不
  包含：secret、atomPath、etag、atom_body、状态/时间戳 —— 秘密与
  运行状态不是配置；
- 导入：逐条目重新选择本实例凭据引用：
  * credentials[ref] = "generate" → 新建来源并铸造新凭据（凭据只在
    创建时存在于该来源，导入响应**不回显**任何秘密 —— 用户随后走
    既有 per-source 凭据流程获取订阅 URL）；
  * credentials[ref] = 既有来源 uuid → 把配置**合并进该来源**（保留
    其既有凭据 —— 这就是「重新选择本实例凭据引用」）；
  * 缺失/未知 ref → 该条目跳过，原因如实进 skipped；
- 防重复导入：包摘要（canonical JSON sha256）唯一 —— 同一包二次
  导入 → 409 already_imported；
- per-user：导入目标与既有来源都在 per-user 库，A 的转移包操作对
  B 不可见。
"""

import hashlib
import json
from typing import Any

from lumirss.api_source_store import ApiSourceStore
from lumirss.storage import Database
from lumirss.util import utc_now

BUNDLE_VERSION = 1
_MAX_BUNDLE_SOURCES = 100


class TransferBundleInvalid(ValueError):
    """转移包非法（映射 422）。"""


class TransferAlreadyImported(Exception):
    """同一包已导入过（映射 409）。携带首次导入摘要。"""

    def __init__(self, imported_at: str, created: int, merged: int, skipped: int) -> None:
        super().__init__("bundle already imported")
        self.imported_at = imported_at
        self.created = created
        self.merged = merged
        self.skipped = skipped


def bundle_digest(bundle: dict[str, Any]) -> str:
    canonical = json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


async def export_bundle(store: ApiSourceStore) -> dict[str, Any]:
    """导出全部 API 来源的配置（无秘密）。"""
    records = await store.list_sources()
    sources: list[dict[str, Any]] = []
    for record in records:
        sources.append(
            {
                "credentialRef": f"apisource:{record.uuid}",
                "name": record.name,
                "endpoint": record.endpoint,
                "itemsExpr": record.items_expr,
                "fieldMap": json.loads(record.field_map),
                "pagination": json.loads(record.pagination or "{}"),
                "maxRunsPerHour": record.max_runs_per_hour,
            }
        )
    return {
        "version": BUNDLE_VERSION,
        "kind": "lumirss-api-intake",
        "exportedAt": utc_now(),
        "sources": sources,
        "honestyNote": "包内不含任何秘密与运行状态；导入时需为每个 credentialRef 重新选择本实例凭据引用。",
    }


def _clean_import_entry(entry: Any) -> dict[str, Any]:
    from lumirss.api_sources import (
        validate_field_map,
        validate_items_expr,
        validate_pagination,
    )

    if not isinstance(entry, dict):
        raise TransferBundleInvalid("sources 条目必须是对象。")
    ref = entry.get("credentialRef")
    if not isinstance(ref, str) or not ref.strip():
        raise TransferBundleInvalid("sources 条目缺少 credentialRef。")
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        raise TransferBundleInvalid("sources 条目缺少 name。")
    endpoint = entry.get("endpoint")
    if not isinstance(endpoint, str):
        raise TransferBundleInvalid("sources 条目缺少 endpoint。")
    items_expr = validate_items_expr(str(entry.get("itemsExpr", "")))
    field_map = entry.get("fieldMap")
    if not isinstance(field_map, dict):
        raise TransferBundleInvalid("sources 条目缺少 fieldMap。")
    clean_fields = validate_field_map({k: str(v) for k, v in field_map.items()})
    pagination = entry.get("pagination", {"mode": "none"})
    clean_pagination = validate_pagination(pagination if isinstance(pagination, dict) else {})
    budget = entry.get("maxRunsPerHour", 4)
    if isinstance(budget, bool) or not isinstance(budget, int) or not 1 <= budget <= 60:
        raise TransferBundleInvalid("maxRunsPerHour 必须在 1..60 之间。")
    return {
        "credentialRef": ref.strip(),
        "name": name.strip(),
        "endpoint": endpoint.strip(),
        "itemsExpr": items_expr,
        "fieldMap": json.loads(clean_fields),
        "pagination": json.loads(clean_pagination),
        "maxRunsPerHour": budget,
    }


class TransferBundleStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def import_bundle(
        self,
        sources_store: ApiSourceStore,
        bundle: dict[str, Any],
        credentials: dict[str, str] | None,
    ) -> dict[str, Any]:
        """导入转移包；凭据引用逐条目决定 新建(generate)/合并(uuid)/跳过。

        返回 {created, merged, skipped, digest}；created 条目**不含秘密**。"""
        if not isinstance(bundle, dict):
            raise TransferBundleInvalid("bundle 必须是对象。")
        if bundle.get("kind") != "lumirss-api-intake" or bundle.get("version") != BUNDLE_VERSION:
            raise TransferBundleInvalid("不支持的转移包（kind/version 不匹配）。")
        raw_sources = bundle.get("sources")
        if not isinstance(raw_sources, list) or not raw_sources:
            raise TransferBundleInvalid("bundle.sources 必须是非空数组。")
        if len(raw_sources) > _MAX_BUNDLE_SOURCES:
            raise TransferBundleInvalid(f"转移包最多 {_MAX_BUNDLE_SOURCES} 个来源。")
        digest = bundle_digest(
            {**bundle, "exportedAt": bundle.get("exportedAt", "")}
        )
        await self._db.migrate()
        existing = await self._db.fetch_one(
            "SELECT imported_at, created_count, merged_count, skipped_count FROM api_transfer_imports "
            "WHERE bundle_digest = ?",
            (digest,),
        )
        if existing is not None:
            raise TransferAlreadyImported(
                str(existing["imported_at"]),
                int(existing["created_count"]),
                int(existing["merged_count"]),
                int(existing["skipped_count"]),
            )
        credentials = credentials or {}
        if not isinstance(credentials, dict):
            raise TransferBundleInvalid("credentials 必须是对象。")
        created: list[dict[str, Any]] = []
        merged: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for raw in raw_sources:
            try:
                entry = _clean_import_entry(raw)
            except TransferBundleInvalid as exc:
                skipped.append({"name": "?", "reason": str(exc)})
                continue
            ref = entry["credentialRef"]
            choice = credentials.get(ref)
            if not isinstance(choice, str) or not choice.strip():
                skipped.append(
                    {"name": entry["name"], "reason": "未选择凭据引用（credentials 缺少该 credentialRef）。"}
                )
                continue
            choice = choice.strip()
            if choice == "generate":
                try:
                    record = await sources_store.create(
                        name=entry["name"],
                        endpoint=entry["endpoint"],
                        items_expr=entry["itemsExpr"],
                        field_map=entry["fieldMap"],
                        pagination=entry["pagination"],
                        max_runs_per_hour=entry["maxRunsPerHour"],
                    )
                except Exception as exc:
                    skipped.append({"name": entry["name"], "reason": f"新建失败：{exc}"})
                    continue
                # 新凭据（record.secret）只在 create 返回里存在一次；
                # 导入响应不回显 —— 用户走既有 per-source 凭据流程获取。
                created.append(
                    {
                        "uuid": record.uuid,
                        "name": record.name,
                        "credentialRef": ref,
                        "credentialNote": "已铸造新凭据；请通过该来源的凭据入口获取订阅地址。",
                    }
                )
            else:
                target = await sources_store.get(choice)
                if target is None:
                    skipped.append(
                        {"name": entry["name"], "reason": "凭据引用指向的既有来源不存在。"}
                    )
                    continue
                updated = await sources_store.update(
                    choice,
                    name=entry["name"],
                    endpoint=entry["endpoint"],
                    items_expr=entry["itemsExpr"],
                    field_map=entry["fieldMap"],
                    pagination=entry["pagination"],
                    max_runs_per_hour=entry["maxRunsPerHour"],
                )
                merged.append(
                    {
                        "uuid": updated.uuid if updated else choice,
                        "name": entry["name"],
                        "credentialRef": ref,
                    }
                )
        await self._db.execute(
            "INSERT INTO api_transfer_imports (bundle_digest, imported_at, created_count, merged_count, skipped_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (digest, utc_now(), len(created), len(merged), len(skipped)),
        )
        return {
            "created": created,
            "merged": merged,
            "skipped": skipped,
            "digest": digest,
        }
