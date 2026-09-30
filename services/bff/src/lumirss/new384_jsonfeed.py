"""NEW-384 JSON Feed 个人导出 —— 把用户选定的本人资料视图导出为标准
JSON Feed 1.1，并如实说明包含的字段与授权范围。

口径：

- 范围（scope）由用户显式选择：``clips``（本人的剪藏文章）、``bib``
  （本人的书目记录），可同时选；导出前逐范围清点条数；
- 标准字段：version / title / description / items[]；item 用 id、
  url、title、content_html、content_text、date_published、authors、
  tags 中该条实际有的字段——不虚造空字段；
- 扩展（JSON Feed 1.1 允许下划线前缀私有扩展）：``_lumi`` 携带
  fieldsIncluded（实际包含的字段清单）与 authorizationScope（授权
  范围说明：只含本人资料、不含他人数据、不含凭据）；
- 零网络；feed 即时返回（JSON 响应或 .json 下载），台账只存范围、
  条数、字段清单与授权说明文本。

per-user：数据面全部来自 member 自己的库。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.new381_bib import BibStore
from lumirss.storage import Database
from lumirss.util import utc_now

FEED_VERSION = "https://jsonfeed.org/version/1.1"
_SCOPES = ("clips", "bib")
_AUTHORIZATION_SCOPE = (
    "只包含当前登录账户本人选定的资料视图（剪藏/书目）；不含其他账户"
    "的数据、不含凭据或服务端秘密；导出文件由导出者自行决定存放与"
    "再分发，Lumi 不追踪文件去向。"
)


class FeedScopeInvalid(ValueError):
    """导出范围非法（映射 400）。"""


def _clean(value: Any, limit: int = 1000) -> str:
    return str(value or "").strip()[:limit]


async def build_feed(db: Database, scopes: list[str]) -> dict[str, Any]:
    """按选定范围组装 JSON Feed 1.1 字典（零写入）。"""
    await db.migrate()
    clean_scopes: list[str] = []
    for scope in scopes:
        scope = _clean(scope, 20)
        if scope not in _SCOPES:
            raise FeedScopeInvalid(f"未知导出范围：{scope}（可选 {'/'.join(_SCOPES)}）")
        if scope not in clean_scopes:
            clean_scopes.append(scope)
    if not clean_scopes:
        raise FeedScopeInvalid("请至少选择一个导出范围（clips / bib）。")

    items: list[dict[str, Any]] = []
    fields: set[str] = set()
    clip_count = bib_count = 0

    if "clips" in clean_scopes:
        rows = await db.fetch_all(
            "SELECT item_uuid, url, title, byline, content_html, content_text,"
            " created_at FROM library_clips"
            " ORDER BY created_at DESC, item_uuid ASC LIMIT 2000"
        )
        for row in rows:
            item: dict[str, Any] = {
                "id": f"lumi-clip:{row['item_uuid']}",
                "title": _clean(row["title"], 500),
                "url": _clean(row["url"], 2048),
                "content_html": str(row["content_html"] or ""),
                "content_text": _clean(row["content_text"], 200000),
                "date_published": _clean(row["created_at"], 40),
            }
            byline = _clean(row["byline"], 200)
            if byline:
                item["authors"] = [{"name": byline}]
                fields.add("authors")
            items.append(item)
            fields.update(
                key for key in ("id", "title", "url", "content_html",
                                "content_text", "date_published")
            )
            clip_count += 1

    if "bib" in clean_scopes:
        records = await BibStore(db).list_records()
        for record in records:
            item = {
                "id": f"lumi-bib:{record['id']}",
                "title": record["title"],
                "content_text": record["abstract"],
                "date_published": record["createdAt"],
            }
            if record["url"]:
                item["url"] = record["url"]
                fields.add("url")
            if record["tags"]:
                item["tags"] = record["tags"]
                fields.add("tags")
            if record["creators"]:
                item["authors"] = [{"name": name} for name in record["creators"]]
                fields.add("authors")
            items.append(item)
            fields.update(("id", "title", "content_text", "date_published"))
            bib_count += 1

    if not items:
        raise FeedScopeInvalid("选定范围内没有可导出的资料。")

    field_list = sorted(fields)
    feed: dict[str, Any] = {
        "version": FEED_VERSION,
        "title": "LumiRSS 个人资料导出",
        "description": (
            f"本人资料视图导出（范围：{' + '.join(clean_scopes)}；"
            f"共 {len(items)} 条）。{_AUTHORIZATION_SCOPE}"
        ),
        "items": items,
        "_lumi": {
            "fieldsIncluded": field_list,
            "authorizationScope": _AUTHORIZATION_SCOPE,
            "scopes": clean_scopes,
            "exportedAt": utc_now(),
        },
    }
    return feed


async def persist_export(db: Database, feed: dict[str, Any]) -> str:
    await db.migrate()
    export_id = f"jsonfeed-{_uuid.uuid4().hex[:12]}"
    meta = feed["_lumi"]
    clip_count = sum(1 for item in feed["items"] if str(item["id"]).startswith("lumi-clip:"))
    bib_count = sum(1 for item in feed["items"] if str(item["id"]).startswith("lumi-bib:"))
    await db.execute(
        "INSERT INTO new384_feed_exports"
        " (id, scope, clip_count, bib_count, fields_json, authorization_scope,"
        " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            export_id,
            "+".join(meta["scopes"]),
            clip_count,
            bib_count,
            json.dumps(meta["fieldsIncluded"], ensure_ascii=False),
            meta["authorizationScope"],
            utc_now(),
        ),
    )
    return export_id


async def list_exports(db: Database) -> list[dict[str, Any]]:
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT id, scope, clip_count, bib_count, fields_json,"
        " authorization_scope, created_at FROM new384_feed_exports"
        " ORDER BY created_at DESC, id ASC LIMIT 100"
    )
    return [
        {
            "id": str(row["id"]),
            "scope": str(row["scope"]),
            "clipCount": int(row["clip_count"]),
            "bibCount": int(row["bib_count"]),
            "fieldsIncluded": json.loads(str(row["fields_json"])),
            "authorizationScope": str(row["authorization_scope"]),
            "createdAt": str(row["created_at"]),
        }
        for row in rows
    ]
