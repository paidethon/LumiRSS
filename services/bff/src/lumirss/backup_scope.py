"""N185 备份内容选择（scope）——预览与快照裁剪的唯一入口。

范围语义：完整备份默认包含全部四个用户数据组件（workspaces / notes /
annotations / sourceConfig）。选择范围只作用于「本用户库」的这四类；
以下内容永远排除、不可选入（always-excluded）：

- 凭据与密钥（secrets.json / RSSHub 凭据 / API Key）——从不进入备份；
- FreshRSS 内容（订阅与文章状态由 FreshRSS 持有，属实例级数据）。

预览与快照裁剪共用同一张组件→表映射（口径一致）。裁剪发生在
lumi.sqlite 的「在线备份快照副本」上，绝不触碰运行中的库；被排除
组件的行按子表→父表顺序删除（外键关闭，表存在性逐个核对——旧库缺
表时如实跳过）。
"""

import sqlite3
from typing import Any

from lumirss.storage import Database

SCOPE_COMPONENTS = ("workspaces", "notes", "annotations", "sourceConfig")

# 永远排除（对浏览器只含类别名，绝不含任何值）。
ALWAYS_EXCLUDED = [
    "凭据与密钥（API Key / WebDAV / RSSHub / IMAP 密码；恢复后需重新配置）",
    "FreshRSS 内容（订阅与文章状态由 FreshRSS 持有，不随用户数据范围裁剪）",
]

# 组件 → 需要从快照中清除的表（子表在前，父表在后；排除该组件时逐表
# DELETE）。统计口径 = 各表 COUNT 之和。
_COMPONENT_TABLES: dict[str, tuple[str, ...]] = {
    "workspaces": (
        "workspace_section_items",
        "workspace_sections",
        "workspace_item_status",
        "workspace_goals",
        "workspace_snapshots",
        "workspace_resume",
        "workspace_cleanup_log",
        "workspace_templates",
        "workspace_items",
        "workspaces",
    ),
    "notes": ("lumi_notes",),
    "annotations": ("annotations",),
    "sourceConfig": ("api_sources", "staged_sources", "source_overrides"),
}


def normalize_include(raw: Any) -> dict[str, bool]:
    """请求体 include → 全键布尔（缺省/非法值 = True，即默认全包含）。

    接受裸 dict 或 pydantic 模型（路由体字段是 BackupScopeInclude 实例）。"""
    include = {component: True for component in SCOPE_COMPONENTS}
    if raw is None:
        return include
    if not isinstance(raw, dict) and hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    if isinstance(raw, dict):
        for component in SCOPE_COMPONENTS:
            if component in raw:
                include[component] = bool(raw[component])
    return include


def is_full_scope(include: dict[str, bool]) -> bool:
    return all(include[c] for c in SCOPE_COMPONENTS)


async def preview_scope_counts(
    db: Database, include: dict[str, bool]
) -> list[dict[str, Any]]:
    """逐组件（含排除）给出将进入备份的行数；只读当前请求者的库。

    排除的组件 count 如实为 0（不会进入备份），并以 included=false
    区分「本来就没有」与「被范围排除」。隔离语义：计数只来自当前
    请求路由到的每用户库——其它用户的数据在结构上不可见。"""
    await db.migrate()
    rows: list[dict[str, Any]] = []
    for component in SCOPE_COMPONENTS:
        count = 0
        if include[component]:
            for table in _COMPONENT_TABLES[component]:
                row = await db.fetch_one(f"SELECT COUNT(*) AS n FROM {table}")
                if row is not None:
                    count += int(row["n"])
        rows.append(
            {
                "component": component,
                "included": include[component],
                "count": count,
            }
        )
    return rows


def apply_scope_to_snapshot(path: Any, include: dict[str, bool]) -> None:
    """在 lumi.sqlite 快照副本上清除被排除组件的行（同步，worker 线程
    调用）。绝不修改运行中的库；只处理确实存在的表。"""
    connection = sqlite3.connect(str(path), timeout=5.0)
    try:
        existing = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        connection.execute("PRAGMA foreign_keys = OFF")
        for component in SCOPE_COMPONENTS:
            if include[component]:
                continue
            for table in _COMPONENT_TABLES[component]:
                if table in existing:
                    connection.execute(f"DELETE FROM {table}")
        connection.commit()
    finally:
        connection.close()
