"""F39 Lumi 自有数据可携带导出 —— 只读聚合为版本化 JSON。

与运维备份（0018 全量归档）和单工作区研究包分开：本导出面向「换设备
带走我的整理成果」——工作区（含成员引用）、标签与条目绑定、书签笔记、
GPT 日报配置与期刊（标题/结构/引用，不含订阅 token）。

明确不包含（各自另有出口）：FreshRSS 订阅（既有 OPML 导出）、Vault
（只读投影不属于 Lumi 自有内容）、服务密钥、Agent 会话与审批。
"""

import json
from typing import Any

from lumirss.gpt_digest_configs import GptDigestConfigStore
from lumirss.gpt_digest_issues import GptDigestIssuesStore
from lumirss.library import LibraryStore
from lumirss.tags import TagStore
from lumirss.util import utc_now
from lumirss.workspaces import RESERVED_WORKSPACE_ID, WorkspaceStore

EXPORT_SCHEMA_VERSION = 1
_MAX_ISSUES_PER_CONFIG = 30
_MAX_TAG_REFS = 200


async def build_lumi_data_export(db: Any) -> dict[str, Any]:
    """聚合全部 Lumi 自有域（只读；单次请求，各域内部已有界）。"""
    workspace_store = WorkspaceStore(db)
    library_store = LibraryStore(db)
    tag_store = TagStore(db)
    config_store = GptDigestConfigStore(db)
    issue_store = GptDigestIssuesStore(db)

    workspaces: list[dict[str, Any]] = []
    for summary in await workspace_store.list_workspaces():
        members = await workspace_store.list_items(summary.id, limit=500)
        workspaces.append(
            {
                "id": summary.id,
                "name": summary.name,
                "description": summary.description,
                "reserved": summary.reserved,
                "itemRefs": [member.item_ref for member in members],
            }
        )

    bookmarks = await library_store.list_all_bookmarks()
    tags = await tag_store.list_tags()
    tag_bindings: list[dict[str, Any]] = []
    for tag in tags[:_MAX_TAG_REFS]:
        refs = await tag_store.item_refs_for_tag(tag.id, limit=_MAX_TAG_REFS)
        tag_bindings.append({"tag": tag.name, "itemRefs": refs})

    configs = await config_store.list_configs()
    digest_configs: list[dict[str, Any]] = []
    digest_issues: list[dict[str, Any]] = []
    for config in configs:
        digest_configs.append(
            {
                "id": config["id"],
                "name": config["name"],
                "hour": config["hour"],
                "timezone": config["timezone"],
                "windowHours": config["windowHours"],
                "limitCount": config["limitCount"],
                "perSourceCap": config["perSourceCap"],
                "feedUrlAllow": config["feedUrlAllow"],
                "sourceKind": config["sourceKind"],
                "slots": config["slots"],
            }
        )
        for row in await issue_store.recent_issues(config["id"], _MAX_ISSUES_PER_CONFIG):
            try:
                sections = json.loads(str(row["sections_json"] or "[]"))
            except ValueError:
                sections = []
            try:
                refs = json.loads(str(row["refs_json"] or "{}"))
            except ValueError:
                refs = {}
            digest_issues.append(
                {
                    "configId": config["id"],
                    "issueKey": str(row["issue_key"]),
                    "title": str(row["title"]),
                    "sections": sections,
                    "refs": refs,
                    "publishedAt": str(row["published_at"]),
                }
            )

    read_later = next(
        (w for w in workspaces if w["id"] == RESERVED_WORKSPACE_ID), None
    )
    return {
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "kind": "lumirss-lumi-data",
        "exportedAt": utc_now(),
        "workspaces": workspaces,
        "readLaterRefs": read_later["itemRefs"] if read_later else [],
        "bookmarks": [
            {
                "itemType": b.item_type,
                "url": b.url,
                "rssItemRef": b.rss_item_ref,
                "title": b.title,
                "note": b.note,
                "createdAt": b.created_at,
            }
            for b in await library_store.list_all_bookmarks()
        ],
        "tags": [
            {"name": tag.name, "count": tag.count} for tag in tags
        ],
        "tagBindings": tag_bindings,
        "digestConfigs": digest_configs,
        "digestIssues": digest_issues,
    }


