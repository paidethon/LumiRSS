"""NEW-281..290 共享测试工具 —— 相对时间播种（n049 教训：绝不固定日历日期）。

所有播种时间都用 ``datetime.now(UTC) - timedelta(...)`` 推导，窗口边界
测试从 GET /window 读回真实边界后再推导迟到/窗口内时刻，保证与墙钟
和时区无关地稳定。
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from new2xx_ab import seed_entry as _ab_seed_entry


def iso(**delta: Any) -> str:
    """now(UTC) 加上给定 delta 后的 ISO 串（timedelta 关键字直传）。"""
    return (datetime.now(UTC) + timedelta(**delta)).isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def seed(
    env: dict[str, Any],
    who: str,
    *,
    title: str = "测试文章",
    content_text: str = "",
    published: str | None = None,
    starred: int = 0,
    read: int = 0,
) -> dict[str, str]:
    """给指定成员播一篇 search_entries 文章；返回 entryRef/itemId。"""
    seed_id = uuid.uuid4().hex
    item_id = f"tag:google.com,2005:reader/item/{seed_id.zfill(16)}"
    stamp = published or iso(hours=-24)
    entry_ref = _ab_seed_entry(
        env,
        who,
        item_id,
        read=read,
        title=title,
        content_text=content_text,
        published_at=stamp,
    )
    from lumirss.entryref import decode_entry_ref

    if starred:
        # 共享 seed_entry 夹具没有 starred 形参——显式补标（同用户作用域）。
        from lumirss.user_scope import user_context

        async def _star():
            await env["app"].state.db.execute(
                "UPDATE search_entries SET starred = 1 WHERE item_id = ?",
                (item_id,),
            )

        with user_context(env[who]["userId"]):
            asyncio.run(_star())

    return {
        "entryRef": entry_ref.removeprefix("rss:"),
        "itemId": decode_entry_ref(entry_ref.removeprefix("rss:")),
        "itemIdSeed": item_id,
        "title": title,
        "publishedAt": stamp,
    }


def make_item(
    card: dict[str, str],
    section_key: str,
    *,
    provenance: str = "manual",
    pull_back: bool = False,
    dup_decision: str | None = None,
) -> dict[str, Any]:
    """编排台条目负载：摘要卡字段 + 栏目 + 编辑来源/窗口/去重决定。"""
    payload: dict[str, Any] = {
        "entryRef": card["entryRef"],
        "sectionKey": section_key,
        "itemId": card.get("itemId", ""),
        "title": card.get("title", ""),
        "feedTitle": card.get("feedTitle", ""),
        "url": card.get("url", ""),
        "publishedAt": card.get("publishedAt", ""),
        "excerpt": card.get("excerpt", ""),
        "provenance": provenance,
        "pullBack": pull_back,
    }
    if dup_decision is not None:
        payload["dupDecision"] = dup_decision
    return payload


def create_issue(
    client: Any,
    headers: dict[str, str],
    *,
    title: str,
    cards: list[dict[str, str]],
    sections: list[dict[str, str]] | None = None,
    range_from: str = "",
    range_to: str = "",
    provenance: str = "manual",
    extra_items: list[dict[str, Any]] | None = None,
) -> Any:
    """一步建稿：单栏目 + 全部卡片按序入刊（测试主路径便捷封装）。"""
    body: dict[str, Any] = {
        "title": title,
        "rangeFrom": range_from,
        "rangeTo": range_to,
        "sections": sections or [{"key": "main", "label": "正文"}],
        "items": [
            make_item(card, (sections or [{"key": "main"}])[0]["key"], provenance=provenance)
            for card in cards
        ],
    }
    if extra_items:
        body["items"] = extra_items
    return client.post("/api/v1/briefings", json=body, headers=headers)


def confirm(client: Any, headers: dict[str, str], issue_id: str) -> Any:
    return client.post(f"/api/v1/briefings/{issue_id}/confirm", headers=headers)


def get_issue(client: Any, headers: dict[str, str], issue_id: str) -> Any:
    return client.get(f"/api/v1/briefings/{issue_id}", headers=headers)


def run(coro: Any) -> Any:
    return asyncio.run(coro)
