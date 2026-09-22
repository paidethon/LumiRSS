"""F061 保存视图私有 Atom 订阅 — 公开路由 + 视图→搜索条件映射。

- GET /feeds/views/{view_id}.{secret}.atom：公开免登录（路径不在
  /api/ 下，与 api_sources 的 /feeds/* 免认证模式同一机制）；
- token 错/未启用/视图缺失 → 同一 404（不泄露存在性）；
- 按视图 filters_json + q 走真实搜索管线渲染（稳定 GUID = entry_ref
  的 sha256 前缀；≤100 条；feed title 诚实标注视图名 + 生成时间）；
- ``view_search_params`` 是视图意图→搜索参数的唯一映射器，F075
  视图对照复用同一口径，两边不会漂移。
"""

import hashlib
import secrets as _secrets
from typing import Any

from fastapi import APIRouter, Request, Response

from lumirss.atom_render import AtomEntry, render_feed, rfc3339
from lumirss.deps import _get_search_service
from lumirss.saved_search_store import SavedSearchStore
from lumirss.token_hash import verify_token

router = APIRouter()

# F061：单次渲染的条目上限（诚实截断——订阅不是全量导出）。
_MAX_FEED_ENTRIES = 100


def new_view_feed_secret() -> str:
    """High-entropy per-view credential（secrets 风格随机 hex）。"""
    return _secrets.token_hex(16)


def view_search_params(view: dict[str, Any]) -> dict[str, Any]:
    """视图存储意图 → SearchIndexService.search 关键字参数。

    filters_json（F017 构建器）叠加 params 基础范围（view=all/unread/
    starred、categoryKey）；feedRef 与 categoryKey 互斥（与 /api/v1/search
    同一约束，feedRef 优先）。"""
    filters = view.get("filters") or {}
    params = view.get("params") or {}
    base_view = str(params.get("view") or "all")
    feed_ref = filters.get("feedRef") or None
    category_key = params.get("categoryKey") or None
    return {
        "query": str(view.get("query") or ""),
        "feed_url": feed_ref,
        "category_id": None if feed_ref else category_key,
        "unread_only": bool(filters.get("unreadOnly")) or base_view == "unread",
        "starred_only": bool(filters.get("favoriteOnly")) or base_view == "starred",
        "published_from": filters.get("from") or None,
        "published_to": filters.get("to") or None,
        "intitle": filters.get("intitle") or None,
        "phrase": filters.get("phrase") or None,
        "exclude": filters.get("exclude") or None,
        "has_summary": filters.get("hasSummary"),
    }


def stable_entry_guid(entry_ref: str) -> str:
    """稳定 GUID：entry_ref 的 sha256 前缀（同一 entry 永远同一 id）。"""
    return "urn:lumi:entry:" + hashlib.sha256(entry_ref.encode("utf-8")).hexdigest()[:32]


@router.get("/feeds/views/{view_id}.{secret}.atom")
async def saved_view_atom(view_id: str, secret: str, request: Request) -> Response:
    """保存视图的私有 Atom 订阅（公开免登录；token 错 → 404 不泄露）。

    0067：路径 token 先经 token_owner_index 解析归属用户——同一 404
    不泄露存在性，也绝不落入别人的数据作用域。"""
    from lumirss.machine_auth import machine_user_context

    async with machine_user_context(request, secret) as uid:
        if uid is None:
            return Response(
                status_code=404,
                media_type="application/xml",
                content="<error>not found</error>",
            )
        store = SavedSearchStore(request.app.state.db)
        view = await store.get(view_id)
        stored_secret = await store.get_feed_secret(view_id)
        if (
            view is None
            or stored_secret is None
            or not verify_token(secret, stored_secret)
        ):
            return Response(
                status_code=404,
                media_type="application/xml",
                content="<error>not found</error>",
            )
        params = view_search_params(view)
        if not params["query"].strip():
            return Response(
                status_code=404,
                media_type="application/xml",
                content="<error>not found</error>",
            )
        service = _get_search_service(request)
        result = await service.search(limit=_MAX_FEED_ENTRIES, **params)
        from lumirss.util import utc_now

        generated_at = rfc3339(utc_now()) or utc_now()
        entries = [
            AtomEntry(
                entry_id=stable_entry_guid(str(item["entryRef"])),
                title=str(item["title"]),
                updated=rfc3339(item["publishedAt"]) or generated_at,
                link=item.get("url"),
                author=item.get("author") or item.get("feedTitle"),
                content_html=str(item.get("snippet") or ""),
                published=rfc3339(item["publishedAt"]),
            )
            for item in result["rows"][:_MAX_FEED_ENTRIES]
        ]
        atom = render_feed(
            feed_id=f"urn:lumi:view-feed:{view_id}",
            title=f"{view['name']} · LumiRSS 保存视图（生成于 {generated_at}）",
            updated=generated_at,
            self_href=str(request.url),
            entries=entries,
            feed_author="LumiRSS",
        )
        return Response(content=atom, media_type="application/atom+xml; charset=utf-8")
