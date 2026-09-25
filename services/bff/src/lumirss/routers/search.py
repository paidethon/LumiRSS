"""Global search routes (0022).

GET /api/v1/search — one page of hits over the derived projection.
POST /api/v1/search/rebuild — explicit bounded rebuild (admin op).
POST /api/v1/search/parse-query — N142 rule-based natural-language →
  structured filters preprocessor (no model calls).
POST /api/v1/search/why-missed — N143 miss diagnosis for one owned entry.
GET /api/v1/search/distribution — N145 per-source/per-day aggregates.

Every parameter is validated here; the projection query itself is a
single static statement (see search_store.py). Snippets are plain text
extracted from the sanitized content text — the web client renders
them as text, never as HTML.
"""

import time
from typing import Any, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, Field

from lumirss.models import (
    SavedSearchCount,
    SavedSearchCreate,
    SavedSearchList,
    SavedSearchPinOrder,
    SavedSearchRename,
    SavedSearchScopeUnlinkResult,
    SavedSearchView,
    SearchDistributionResult,
    SearchParseQueryBody,
    SearchParseRecognized,
    SearchParseResult,
    SearchRebuildResult,
    SearchResponse,
    SearchSnapshotCompareResult,
    SearchSnapshotCreate,
    SearchSnapshotList,
    SearchSnapshotRankChange,
    SearchSnapshotView,
    SearchTimelineAnnotation,
    SearchTimelineMonth,
    SearchTimelineResult,
    SearchWhyMissedBody,
    SearchWhyMissedEntry,
    SearchWhyMissedReason,
    SearchWhyMissedResult,
    ViewFeedTokenResult,
)
from lumirss.saved_search_store import (
    SavedSearchNotFound,
    SavedSearchStore,
)
from lumirss.search_index import (
    SearchQueryError,
    decode_search_cursor,
    encode_search_cursor,
)
from lumirss.search_library import (
    decode_library_search_cursor,
    encode_library_search_cursor,
)
from lumirss.search_snapshot_store import (
    SearchSnapshotNotFound,
    SearchSnapshotStore,
)

from ..deps import _get_search_service

router = APIRouter()

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 50


@router.get(
    "/api/v1/search",
    response_model=SearchResponse,
    response_model_exclude_none=False,
)
async def search(
    request: Request,
    q: str,
    cursor: str | None = None,
    libraryCursor: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    feedUrl: str | None = None,
    categoryId: str | None = None,
    state: str | None = None,
    favorite: bool | None = None,
    from_: str | None = None,
    to: str | None = None,
    intitle: str | None = None,
    phrase: str | None = None,
    exclude: str | None = None,
    hasSummary: bool | None = None,
    expandSynonyms: bool = True,
) -> SearchResponse:
    """Global search over the derived projection.

    ``q`` is required (1-200 characters, at most 4 whitespace-split terms).
    ``state`` accepts "unread" (default: all); ``favorite`` filters
    starred entries; ``from``/``to`` are inclusive/exclusive ISO dates
    (YYYY-MM-DD). ``categoryId``/``feedUrl`` scope the search; the two
    are mutually exclusive. F29 advanced conditions (optional):
    ``intitle`` (title-only, ≤2 terms), ``phrase`` (exact phrase),
    ``exclude`` (excluded terms, ≤2) — bound into the cursor scope so
    pagination never drifts across changed conditions.

    Each leg paginates independently: ``cursor`` keys the RSS leg,
    ``libraryCursor`` the library leg; both cursors are bound to the
    query scope and rejected (400) on mismatch. A ``null`` cursor next
    to a non-null ``libraryCursor`` means the RSS leg is exhausted.
    """
    service = _get_search_service(request)
    query = q.strip()
    if not query:
        raise SearchQueryError("Search query is empty.")
    if len(query) > 200:
        raise SearchQueryError("Search query is too long.")
    if limit < 1 or limit > _MAX_LIMIT:
        raise SearchQueryError(
            f"limit must be between 1 and {_MAX_LIMIT}."
        )
    if feedUrl is not None and categoryId is not None:
        raise SearchQueryError(
            "feedUrl and categoryId are mutually exclusive."
        )
    unread_only = False
    if state is not None:
        if state != "unread":
            raise SearchQueryError('state only supports "unread".')
        unread_only = True
    started = time.time()
    rss_scope: dict[str, Any] = {
        "q": query,
        "feedUrl": feedUrl,
        "categoryId": categoryId,
        "unread": unread_only,
        "favorite": bool(favorite),
        "from": from_,
        "to": to,
        "intitle": (intitle or "").strip() or None,
        "phrase": (phrase or "").strip() or None,
        "exclude": (exclude or "").strip() or None,
        # F017：仅摘要维度（进 cursor scope，翻页不漂移）
        "hasSummary": hasSummary,
        # F078：同义词扩展（进 cursor scope，翻页不漂移）
        "expandSynonyms": expandSynonyms,
    }
    library_scope: dict[str, Any] = {"q": query, "favorite": bool(favorite)}
    # Cursor decoding happens outside the per-leg try blocks: a bad or
    # scope-mismatched cursor is a client error (400), never a silent
    # "library temporarily unavailable" string.
    keyset = (
        decode_search_cursor(cursor, scope=rss_scope)
        if cursor is not None
        else None
    )
    library_keyset = (
        decode_library_search_cursor(libraryCursor, scope=library_scope)
        if libraryCursor is not None
        else None
    )
    result: dict[str, Any]
    if cursor is None and libraryCursor is not None:
        # Page contract: only the library leg continues.
        result = {
            "rows": [],
            "hasMore": False,
            "nextKeyset": None,
        }
    else:
        result = await service.search(
            query=query,
            limit=limit,
            keyset=keyset,
            feed_url=feedUrl,
            category_id=categoryId,
            unread_only=unread_only,
            starred_only=bool(favorite),
            published_from=from_,
            published_to=to,
            intitle=intitle,
            phrase=phrase,
            exclude=exclude,
            has_summary=hasSummary,
            expand_synonyms=expandSynonyms,
        )
    next_cursor = None
    if result["hasMore"] and result["nextKeyset"] is not None:
        next_cursor = encode_search_cursor(
            *result["nextKeyset"], scope=rss_scope
        )
    index = await service.index_info()
    # phase2 G6 unified view: the library leg runs beside the RSS leg and
    # fails independently (partial failure stays honest, never silent).
    # A starred (favorite) filter applies to BOTH legs (P0-10j) and is
    # pushed into SQL before LIMIT (pool #11), with its own keyset
    # cursor so hits beyond the first slice stay reachable (pool #10).
    library_items = None
    library_error = None
    library_next_cursor = None
    library_has_more = False
    try:
        from lumirss.deps import _get_library_search_writer
        from lumirss.models import LibrarySearchItem

        writer = _get_library_search_writer(request)
        hits, library_has_more = await writer.search_page(
            query,
            limit=limit,
            favorite_only=bool(favorite),
            keyset=library_keyset,
        )
        if library_has_more and hits:
            last = hits[-1]
            library_next_cursor = encode_library_search_cursor(
                str(last["updated_at"]),
                str(last["ref"]),
                scope=library_scope,
            )
        library_items = [
            LibrarySearchItem(
                ref=str(hit["ref"]),
                kind=str(hit["kind"]),
                title=str(hit["title"]),
                url=hit["url"],
                snippet=str(hit["body"])[:160],
                updatedAt=str(hit["updated_at"]),
            )
            for hit in hits
        ]
    except Exception:  # noqa: BLE001 — leg failure must not kill RSS
        library_error = "库搜索暂不可用，RSS 结果不受影响。"
    return SearchResponse(
        items=result["rows"],
        nextCursor=next_cursor,
        hasMore=result["hasMore"],
        elapsedMs=int((time.time() - started) * 1000),
        index=index,
        library=library_items,
        libraryError=library_error,
        libraryNextCursor=library_next_cursor,
        libraryHasMore=library_has_more,
    )


# ---------------------------------------------------------------------------
# F073：引用清单导出（keyset 全量迭代；CSV 公式注入防护服务端落地）。
# ---------------------------------------------------------------------------


class SearchExportBody(BaseModel):
    """POST /api/v1/search/export body：与 GET /search 同参 + 导出选项。"""

    q: str = Field(min_length=1, max_length=200)
    fields: list[Literal["title", "source", "date", "url", "excerpt"]] = Field(
        default=["title", "source", "date", "url"],
        min_length=1,
        max_length=5,
    )
    format: Literal["csv", "markdown"] = "csv"
    cap: int = Field(default=500, ge=1, le=2000)
    excerptChars: int = Field(default=160, ge=40, le=200)
    feedUrl: str | None = None
    categoryId: str | None = None
    state: str | None = None
    favorite: bool = False
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    intitle: str | None = None
    phrase: str | None = None
    exclude: str | None = None
    hasSummary: bool | None = None
    dryRun: bool = False


_FIELD_HEADERS = {
    "title": "标题",
    "source": "来源",
    "date": "日期",
    "url": "链接",
    "excerpt": "摘录",
}


@router.post("/api/v1/search/export", response_model=None)
async def export_search_results(payload: SearchExportBody, request: Request) -> Response:
    """引用清单导出（F073）：keyset 全量迭代（cap 上限 2000，诚实截断）。

    dryRun=true → 只返回 {total, capped}（UI 范围预览）。文件导出时
    截断标注在 X-Lumi-Truncated / X-Lumi-Total 响应头。导出仅含选中
    字段（excerpt ≤200 字），绝不含正文全文。"""
    from fastapi.responses import JSONResponse, PlainTextResponse

    from lumirss.search_export import build_csv, build_markdown_list

    service = _get_search_service(request)
    query = payload.q.strip()
    if not query:
        raise SearchQueryError("Search query is empty.")

    scope_state = payload.state == "unread"
    keyset = None
    rows: list[dict[str, Any]] = []
    total = 0
    capped = False
    for _ in range(9):  # 8 页 × 250 = 2000 上界 + 1 次收尾
        result = await service.search(
            query=query,
            limit=250,
            keyset=keyset,
            feed_url=payload.feedUrl,
            category_id=payload.categoryId,
            unread_only=scope_state,
            starred_only=payload.favorite,
            published_from=payload.from_,
            published_to=payload.to,
            intitle=payload.intitle,
            phrase=payload.phrase,
            exclude=payload.exclude,
            has_summary=payload.hasSummary,
        )
        total += len(result["rows"])
        rows.extend(result["rows"])
        if not result["hasMore"] or result["nextKeyset"] is None or total >= payload.cap:
            break
        scope = {
            "q": query,
            "feedUrl": payload.feedUrl,
            "categoryId": payload.categoryId,
            "unread": scope_state,
            "favorite": payload.favorite,
            "from": payload.from_,
            "to": payload.to,
            "intitle": payload.intitle,
            "phrase": payload.phrase,
            "exclude": payload.exclude,
            "hasSummary": payload.hasSummary,
        }
        keyset = decode_search_cursor(
            encode_search_cursor(*result["nextKeyset"], scope=scope), scope=scope
        )
    capped = total > payload.cap or (total >= payload.cap and len(rows) > payload.cap)
    rows = rows[: payload.cap]
    if payload.dryRun:
        return JSONResponse({"total": len(rows), "scanned": total, "capped": capped})

    headers = [_FIELD_HEADERS[f] for f in payload.fields]

    def _cell(row: dict[str, Any], field: str) -> str:
        if field == "title":
            return str(row.get("title") or "")
        if field == "source":
            return str(row.get("feedTitle") or "")
        if field == "date":
            return str(row.get("publishedAt") or "")[:10]
        if field == "url":
            return str(row.get("url") or "")
        if field == "excerpt":
            return str(row.get("snippet") or "")[: payload.excerptChars]
        return ""

    table = [[_cell(row, f) for f in payload.fields] for row in rows]
    if payload.format == "csv":
        content = build_csv(headers, table)
    else:
        note = (
            f"已截断：匹配共超过 {payload.cap} 条，仅导出前 {len(rows)} 条。"
            if capped
            else None
        )
        content = build_markdown_list(headers, table, truncated_note=note)
    return PlainTextResponse(
        content,
        media_type="text/csv; charset=utf-8" if payload.format == "csv" else "text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="lumi-search-export.' + ("csv" if payload.format == "csv" else "md") + '"',
            "X-Lumi-Total": str(len(rows)),
            "X-Lumi-Truncated": "1" if capped else "0",
        },
    )


@router.post("/api/v1/search/rebuild", response_model=SearchRebuildResult)
async def rebuild_index(request: Request) -> SearchRebuildResult:
    """Rebuild the projection from FreshRSS (bounded, honest stats)."""
    service = _get_search_service(request)
    report = await service.rebuild()
    return SearchRebuildResult(
        entryCount=report["entryCount"],
        pages=report["pages"],
        partial=report["partial"],
        elapsedMs=report["elapsedMs"],
    )


# -- Saved search views (pool #09) ------------------------------------------


def _get_saved_search_store(request: Request) -> SavedSearchStore:
    from lumirss.deps import _cached_on_app_state

    return _cached_on_app_state(
        request,
        "saved_search_store",
        lambda: SavedSearchStore(request.app.state.db),
    )


def _saved_model(row: dict[str, Any], workspace_ids: set[str]) -> SavedSearchView:
    workspace_id = row.get("workspaceId")
    # N144：scopeBroken = 引用的工作区已不存在（删除后不静默改写视图，
    # 也不伪造成「正常」——由前端给「已失效」横幅 + 解除关联动作）。
    scope_broken = workspace_id is not None and workspace_id not in workspace_ids
    return SavedSearchView(
        id=row["id"],
        name=row["name"],
        query=row["query"],
        view=row["params"].get("view", "all"),
        categoryKey=row["params"].get("categoryKey", ""),
        pinned=row.get("pinned", False),
        pinOrder=row.get("pinOrder"),
        filters=row.get("filters"),
        # F061：只暴露布尔，token 本身绝不返回。
        hasFeedToken=row.get("hasFeedToken", False),
        # N144：检索范围。
        workspaceId=workspace_id,
        contentTypes=row.get("contentTypes"),
        scopeBroken=scope_broken,
        createdAt=row["createdAt"],
        updatedAt=row["updatedAt"],
    )


async def _existing_workspace_ids(request: Request) -> set[str]:
    return await _get_saved_search_store(request).existing_workspace_ids()


@router.get("/api/v1/search/views", response_model=SavedSearchList)
async def list_saved_search_views(request: Request) -> SavedSearchList:
    store = _get_saved_search_store(request)
    rows = await store.list()
    workspace_ids = await _existing_workspace_ids(request)
    return SavedSearchList(items=[_saved_model(row, workspace_ids) for row in rows])


@router.post(
    "/api/v1/search/views", response_model=SavedSearchView, status_code=201
)
async def create_saved_search_view(
    payload: SavedSearchCreate, request: Request
) -> SavedSearchView:
    """Save the current query + filter intent (not the result set)."""
    store = _get_saved_search_store(request)
    # 指向不存在的工作区 → SavedSearchWorkspaceMissing（400
    # workspace_not_found，由 errors.py 稳定映射）。
    row = await store.create(
        payload.name, payload.query,
        {"view": payload.view, "categoryKey": payload.categoryKey},
        workspace_id=payload.workspaceId,
        content_types=payload.contentTypes,
    )
    if payload.filters is not None:
        from lumirss.saved_search_store import normalize_filters

        row = await store.set_filters(row["id"], normalize_filters(payload.filters))
    return _saved_model(row, await _existing_workspace_ids(request))


@router.patch(
    "/api/v1/search/views/{view_id}", response_model=SavedSearchView
)
async def rename_saved_search_view(
    view_id: str, payload: SavedSearchRename, request: Request
) -> SavedSearchView:
    store = _get_saved_search_store(request)
    row = await store.rename(view_id, payload.name)
    if row is None:
        raise SavedSearchNotFound(view_id)
    return _saved_model(row, await _existing_workspace_ids(request))


@router.delete("/api/v1/search/views/{view_id}", status_code=204)
async def delete_saved_search_view(view_id: str, request: Request) -> Response:
    store = _get_saved_search_store(request)
    if not await store.delete(view_id):
        raise SavedSearchNotFound(view_id)
    return Response(status_code=204)


# -- F035 固定保存视图 + 完整意图持久化 + 服务端计数 --------------------------


@router.get("/api/v1/search/views/pinned", response_model=SavedSearchList)
async def list_pinned_views(request: Request) -> SavedSearchList:
    store = _get_saved_search_store(request)
    rows = await store.pinned_views()
    workspace_ids = await _existing_workspace_ids(request)
    return SavedSearchList(items=[_saved_model(row, workspace_ids) for row in rows])


@router.post("/api/v1/search/views/{view_id}/pin", response_model=SavedSearchView)
async def pin_saved_search_view(view_id: str, request: Request) -> SavedSearchView:
    store = _get_saved_search_store(request)
    row = await store.set_pinned(view_id, True)
    if row is None:
        raise SavedSearchNotFound(view_id)
    return _saved_model(row, await _existing_workspace_ids(request))


@router.post("/api/v1/search/views/{view_id}/unpin", response_model=SavedSearchView)
async def unpin_saved_search_view(view_id: str, request: Request) -> SavedSearchView:
    store = _get_saved_search_store(request)
    row = await store.set_pinned(view_id, False)
    if row is None:
        raise SavedSearchNotFound(view_id)
    return _saved_model(row, await _existing_workspace_ids(request))


@router.patch("/api/v1/search/views/{view_id}/pin-order", response_model=SavedSearchView)
async def reorder_pinned_view(
    view_id: str, payload: SavedSearchPinOrder, request: Request
) -> SavedSearchView:
    store = _get_saved_search_store(request)
    row = await store.set_pin_order(view_id, payload.pinOrder)
    if row is None:
        raise SavedSearchNotFound(view_id)
    return _saved_model(row, await _existing_workspace_ids(request))


@router.post(
    "/api/v1/search/views/{view_id}/scope/unlink",
    response_model=SavedSearchScopeUnlinkResult,
)
async def unlink_saved_search_scope(
    view_id: str, request: Request
) -> SavedSearchScopeUnlinkResult:
    """N144：解除已失效的工作区关联（scopeBroken 后的用户显式动作）。

    只清 workspace_id——内容类型范围保留；视图缺失 → 404。"""
    store = _get_saved_search_store(request)
    row = await store.set_workspace_scope(view_id, None)
    if row is None:
        raise SavedSearchNotFound(view_id)
    return SavedSearchScopeUnlinkResult(
        view=_saved_model(row, await _existing_workspace_ids(request))
    )


async def _count_view_matches(request: Request, view: dict[str, Any]) -> dict[str, Any]:
    """复用 search 计数路径（keyset 全量迭代，500/页，2000 封顶诚实上报）。"""
    service = _get_search_service(request)
    filters = view.get("filters") or {}
    unread_only = bool(filters.get("unreadOnly", False))
    favorite_only = bool(filters.get("favoriteOnly", False))
    keyset = None
    total = 0
    capped = False
    for _ in range(8):  # 8 页 × 250 = 2000 上界
        result = await service.search(
            query=view["query"],
            limit=250,
            keyset=keyset,
            feed_url=None,
            category_id=None,
            unread_only=unread_only,
            starred_only=favorite_only,
            published_from=filters.get("from"),
            published_to=filters.get("to"),
            intitle=filters.get("intitle"),
            phrase=filters.get("phrase"),
            exclude=filters.get("exclude"),
            has_summary=filters.get("hasSummary"),
        )
        total += len(result["rows"])
        if not result["hasMore"] or result["nextKeyset"] is None:
            break
        scope = {
            "q": view["query"],
            "feedUrl": None,
            "categoryId": None,
            "unread": unread_only,
            "favorite": favorite_only,
            "from": filters.get("from"),
            "to": filters.get("to"),
            "intitle": filters.get("intitle"),
            "phrase": filters.get("phrase"),
            "exclude": filters.get("exclude"),
            "hasSummary": filters.get("hasSummary"),
        }
        keyset = decode_search_cursor(
            encode_search_cursor(*result["nextKeyset"], scope=scope), scope=scope
        )
    else:
        capped = True
    return {"count": total, "capped": capped, "error": None}


@router.post(
    "/api/v1/search/views/{view_id}/token/enable",
    response_model=ViewFeedTokenResult,
)
async def enable_view_feed_token(view_id: str, request: Request) -> ViewFeedTokenResult:
    """F061：首次启用私有 Atom 订阅，生成 secret（完整路径仅本次返回）。

    已启用 → 409 token_already_active（地址无法二次查看，只能轮换）。"""
    from fastapi.responses import JSONResponse

    from lumirss.routers.view_feed import new_view_feed_secret

    store = _get_saved_search_store(request)
    view = await store.get(view_id)
    if view is None:
        raise SavedSearchNotFound(view_id)
    if view.get("hasFeedToken"):
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "token_already_active",
                    "message": "订阅地址仅在启用时展示一次；如需新地址请轮换。",
                }
            },
        )
    secret = new_view_feed_secret()
    if not await store.set_feed_secret(view_id, secret):
        raise SavedSearchNotFound(view_id)
    from lumirss.machine_auth import index_machine_token

    await index_machine_token(request, secret, "view_feed")
    return ViewFeedTokenResult(
        atomPath=f"/feeds/views/{view_id}.{secret}.atom",
        hasFeedToken=True,
    )


@router.post(
    "/api/v1/search/views/{view_id}/token/rotate",
    response_model=ViewFeedTokenResult,
)
async def rotate_view_feed_token(view_id: str, request: Request) -> ViewFeedTokenResult:
    """F061：轮换 secret —— 旧订阅地址立即失效；新地址仅本次返回。"""
    from lumirss.routers.view_feed import new_view_feed_secret

    store = _get_saved_search_store(request)
    view = await store.get(view_id)
    if view is None:
        raise SavedSearchNotFound(view_id)
    secret = new_view_feed_secret()
    if not await store.set_feed_secret(view_id, secret):
        raise SavedSearchNotFound(view_id)
    from lumirss.machine_auth import index_machine_token

    await index_machine_token(request, secret, "view_feed")
    return ViewFeedTokenResult(
        atomPath=f"/feeds/views/{view_id}.{secret}.atom",
        hasFeedToken=True,
    )


# ---------------------------------------------------------------------------
# F075：视图对照（compare）——两视图各 keyset 全量迭代，纯读取零写入。
# ---------------------------------------------------------------------------


class ViewCompareBody(BaseModel):
    """POST /api/v1/search/views/compare body（F075）。"""

    aId: str
    bId: str


class ViewCompareResult(BaseModel):
    common: list[str] = []
    onlyA: list[str] = []
    onlyB: list[str] = []
    counts: dict[str, int] = {}
    complete: bool = True


async def _collect_view_refs(request: Request, view: dict[str, Any], cap: int) -> tuple[list[str], bool]:
    """单视图 keyset 全量迭代（复用 F075 映射器）；返回 (refs, complete)。"""
    from lumirss.routers.view_feed import view_search_params

    service = _get_search_service(request)
    params = view_search_params(view)
    scope = {
        "q": params["query"],
        "feedUrl": params["feed_url"],
        "categoryId": params["category_id"],
        "unread": params["unread_only"],
        "favorite": params["starred_only"],
        "from": params["published_from"],
        "to": params["published_to"],
        "intitle": params["intitle"],
        "phrase": params["phrase"],
        "exclude": params["exclude"],
        "hasSummary": params["has_summary"],
    }
    refs: list[str] = []
    keyset = None
    complete = True
    for _ in range(9):  # 8 页 × 250 = 2000 上界 + 1 次收尾探测
        result = await service.search(limit=250, keyset=keyset, **params)
        refs.extend(str(row["entryRef"]) for row in result["rows"])
        if not result["hasMore"] or result["nextKeyset"] is None or len(refs) >= cap:
            break
        keyset = decode_search_cursor(
            encode_search_cursor(*result["nextKeyset"], scope=scope), scope=scope
        )
    else:
        complete = False
    if len(refs) > cap:
        refs = refs[:cap]
        complete = False
    return refs, complete


@router.post(
    "/api/v1/search/views/compare",
    response_model=ViewCompareResult,
    response_model_exclude_none=False,
)
async def compare_saved_search_views(payload: ViewCompareBody, request: Request):
    """两视图对照（F075）：common/onlyA/onlyB（refs ≤200）+ 完整计数 +
    complete（任一视图超 2000 上界 → false，诚实不完整）。纯读取零写入；
    视图缺失 → 404。"""
    store = _get_saved_search_store(request)
    view_a = await store.get(payload.aId)
    if view_a is None:
        raise SavedSearchNotFound(payload.aId)
    view_b = await store.get(payload.bId)
    if view_b is None:
        raise SavedSearchNotFound(payload.bId)

    cap = 2000
    refs_a, complete_a = await _collect_view_refs(request, view_a, cap)
    refs_b, complete_b = await _collect_view_refs(request, view_b, cap)
    complete = complete_a and complete_b

    set_a = set(refs_a)
    set_b = set(refs_b)
    common_set = set_a & set_b
    common = [ref for ref in refs_a if ref in set_b][:200]
    only_a = [ref for ref in refs_a if ref not in set_b][:200]
    only_b = [ref for ref in refs_b if ref not in set_a][:200]
    return ViewCompareResult(
        common=common,
        onlyA=only_a,
        onlyB=only_b,
        counts={
            "a": len(set_a),
            "b": len(set_b),
            "common": len(common_set),
            "onlyA": len(set_a - set_b),
            "onlyB": len(set_b - set_a),
        },
        complete=complete,
    )


@router.get("/api/v1/search/views/{view_id}/count", response_model=SavedSearchCount)
async def count_saved_search_view(view_id: str, request: Request) -> SavedSearchCount:
    """固定视图徽标的真实计数；来源失效等查询失败 → error 态而非 0。"""
    store = _get_saved_search_store(request)
    view = await store.get(view_id)
    if view is None:
        raise SavedSearchNotFound(view_id)
    try:
        result = await _count_view_matches(request, view)
    except Exception as exc:  # noqa: BLE001 — 失效视图诚实错误态
        return SavedSearchCount(count=0, capped=False, error=str(exc)[:200])
    return SavedSearchCount(**result)




# ---------------------------------------------------------------------------
# N142：自然语言转过滤条件（纯规则预处理器，无任何模型调用）。
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/search/parse-query",
    response_model=SearchParseResult,
    response_model_exclude_none=False,
)
async def parse_search_query(payload: SearchParseQueryBody, request: Request):
    """N142 帮我转条件：把原始查询里的日期短语 / 来源前缀 / 否定词 /
    引号短语转成与保存视图 filters_json 同构的过滤对象。

    未识别文本保留为 remainingText 并逐词列入 unrecognized（诚实不
    静默丢弃）；来源名解析失败绝不凭空造条件（片段留在自由词中）。
    纯规则，无模型调用。"""
    from datetime import date

    from lumirss.search_parse import parse_query

    service = _get_search_service(request)

    async def _resolve(token: str) -> str | None:
        # 有界 SQL 查询（search_feeds 投影）；投影尚未同步（空表）时
        # 解析失败 → 该片段留在自由词，UI 可见。与搜索同一投影库。
        return await service.store.resolve_source_token(token)

    parsed = await parse_query(
        payload.query,
        today=date.today(),
        resolve_source=_resolve,
    )
    return SearchParseResult(
        filters=parsed.filters,
        remainingText=parsed.remaining_text,
        unrecognized=parsed.unrecognized,
        recognized=[
            SearchParseRecognized(kind=item["kind"], text=item["text"])
            for item in parsed.recognized
        ],
    )


# ---------------------------------------------------------------------------
# N143：为什么没命中 —— 对单条（own-scope）条目复跑过滤链并如实归因。
# ---------------------------------------------------------------------------


def _why_missed_scope(params: dict[str, Any]) -> dict[str, Any]:
    """与 GET /search 的 cursor scope 同构（keyset 绑定，翻页不漂移）。"""
    return {
        "q": params["query"],
        "feedUrl": params["feed_url"],
        "categoryId": params["category_id"],
        "unread": params["unread_only"],
        "favorite": params["starred_only"],
        "from": params["published_from"],
        "to": params["published_to"],
        "intitle": params["intitle"],
        "phrase": params["phrase"],
        "exclude": params["exclude"],
        "hasSummary": params["has_summary"],
    }


async def _why_missed_rank(
    request: Request, *, params: dict[str, Any], entry_ref: str
) -> tuple[int | None, bool]:
    """matched 时的诚实排序位置：keyset 全量迭代复用生产查询路径
    （service.search，2000 上界）——「复跑过滤链」的字面实现。

    返回 (rank, rankCapped)；rank=第几条（最新=1），超出上界 →
    (None, True)。"""
    from lumirss.search_index import decode_search_cursor, encode_search_cursor

    service = _get_search_service(request)
    keyset = None
    rank = 0
    scope = _why_missed_scope(params)
    for _ in range(9):  # 8 页 × 250 = 2000 上界 + 1 次收尾探测
        result = await service.search(
            query=params["query"],
            limit=250,
            keyset=keyset,
            feed_url=params["feed_url"],
            category_id=params["category_id"],
            unread_only=params["unread_only"],
            starred_only=params["starred_only"],
            published_from=params["published_from"],
            published_to=params["published_to"],
            intitle=params["intitle"],
            phrase=params["phrase"],
            exclude=params["exclude"],
            has_summary=params["has_summary"],
            # 聚合/归因口径 = 基础词条过滤链（同 N145，诚实简化）。
            expand_synonyms=False,
        )
        for row in result["rows"]:
            rank += 1
            if str(row["entryRef"]) == entry_ref:
                return rank, False
        if not result["hasMore"] or result["nextKeyset"] is None:
            return None, False
        keyset = decode_search_cursor(
            encode_search_cursor(*result["nextKeyset"], scope=scope),
            scope=scope,
        )
    return None, True


@router.post(
    "/api/v1/search/why-missed",
    response_model=SearchWhyMissedResult,
    response_model_exclude_none=False,
)
async def why_missed(payload: SearchWhyMissedBody, request: Request):
    """N143 排障：对当前用户自己的单条投影行复跑过滤链，如实归因。

    - 每个未通过条件 → 一条 reason（词条/仅标题/短语/排除/来源/分类/
      未读/收藏/日期/摘要），UI 直接展示；
    - 全部通过 → matched=true：条目本应出现在结果中（给按时间排序的
      rank；超出 2000 上界 → rankCapped=true，属排序/分页位置问题）；
    - entryRef 不在本用户作用域（含他人条目）→ 统一 404
      search_entry_not_found，不泄露存在性。"""
    from lumirss.search_debug import SearchEntryNotFound, diagnose_row
    from lumirss.search_index import split_terms

    query = payload.query.strip()
    if not query:
        raise SearchQueryError("Search query is empty.")
    if payload.feedUrl is not None and payload.categoryId is not None:
        raise SearchQueryError(
            "feedUrl and categoryId are mutually exclusive."
        )
    if payload.state is not None and payload.state != "unread":
        raise SearchQueryError('state only supports "unread".')

    # own-scope：RoutingDatabase 已按请求身份路由到本用户库——他人条目
    # 的 ref 在这里「不存在」，与真正缺失走同一个 404。
    store = _get_search_service(request).store
    await store.ensure_migrated()
    row = await store.entry_row_by_ref(payload.entryRef)
    if row is None:
        raise SearchEntryNotFound(
            "条目不在当前账户的搜索索引中，无法诊断。"
        )

    unread_only = payload.state == "unread"
    in_category = True
    if payload.categoryId is not None:
        in_category = await store.feed_in_category(
            category_id=payload.categoryId, feed_url=str(row["feed_url"])
        )
    reasons = diagnose_row(
        row,
        terms=split_terms(query),
        intitle_terms=split_terms(payload.intitle or "")[:2],
        phrase=(payload.phrase or "").strip() or None,
        exclude_terms=split_terms(payload.exclude or "")[:2],
        feed_url=payload.feedUrl,
        in_category=in_category,
        unread_only=unread_only,
        starred_only=bool(payload.favorite),
        published_from=payload.from_,
        published_to=payload.to,
        has_summary=payload.hasSummary,
    )
    entry_meta = SearchWhyMissedEntry(
        entryRef=payload.entryRef,
        title=str(row["title"]),
        feedTitle=str(row["feed_title"]),
        publishedAt=str(row["published_at"]),
    )
    if reasons:
        return SearchWhyMissedResult(
            matched=False,
            reasons=[
                SearchWhyMissedReason(kind=r["kind"], detail=r["detail"])
                for r in reasons
            ],
            entry=entry_meta,
        )
    # 全部条件通过 → 本应命中；给诚实位置（复用生产查询路径迭代）。
    params = {
        "query": query,
        "feed_url": payload.feedUrl,
        "category_id": payload.categoryId,
        "unread_only": unread_only,
        "starred_only": bool(payload.favorite),
        "published_from": payload.from_,
        "published_to": payload.to,
        "intitle": payload.intitle,
        "phrase": payload.phrase,
        "exclude": payload.exclude,
        "has_summary": payload.hasSummary,
    }
    rank, capped = await _why_missed_rank(
        request, params=params, entry_ref=payload.entryRef
    )
    return SearchWhyMissedResult(
        matched=True,
        reasons=[],
        entry=entry_meta,
        rank=rank,
        rankCapped=capped,
    )


# ---------------------------------------------------------------------------
# N145：来源内搜索分布 —— 同参聚合（GROUP BY 在 SQL 完成，正文不出站）。
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/search/distribution",
    response_model=SearchDistributionResult,
    response_model_exclude_none=False,
)
async def search_distribution(
    request: Request,
    q: str,
    feedUrl: str | None = None,
    categoryId: str | None = None,
    state: str | None = None,
    favorite: bool | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    intitle: str | None = None,
    phrase: str | None = None,
    exclude: str | None = None,
    hasSummary: bool | None = None,
):
    """N145 来源分布 + 近 30 天柱状数据：与 GET /search 相同的权限与
    过滤作用域（per-user DB 路由 + 同一过滤链），聚合在 SQL 完成——
    只回每来源/每日计数，绝不搬运正文。

    sources 最多 20 条（超界 → sourcesComplete=false 诚实标注）；
    days 为最近 30 天窗口（补零逐日出，便于直接渲染柱状分布）。
    同义词扩展不参与聚合（与主查询的 OR 扩展腿语义不同：聚合口径 =
    基础词条过滤链，诚实简化）。"""
    from datetime import date, timedelta

    from lumirss.search_index import split_terms

    query = q.strip()
    if not query:
        raise SearchQueryError("Search query is empty.")
    if len(query) > 200:
        raise SearchQueryError("Search query is too long.")
    if feedUrl is not None and categoryId is not None:
        raise SearchQueryError(
            "feedUrl and categoryId are mutually exclusive."
        )
    if state is not None and state != "unread":
        raise SearchQueryError('state only supports "unread".')

    store = _get_search_service(request).store
    await store.ensure_migrated()
    common: dict[str, Any] = dict(
        terms=split_terms(query),
        intitle_terms=split_terms(intitle or "")[:2] or None,
        phrase=(phrase or "").strip() or None,
        exclude_terms=split_terms(exclude or "")[:2] or None,
        feed_url=feedUrl,
        category_id=categoryId,
        unread_only=state == "unread",
        starred_only=bool(favorite),
        published_from=from_,
        published_to=to,
        has_summary=hasSummary,
    )
    total = await store.distribution_total(**common)
    source_rows = await store.distribution_sources(**common, limit=21)
    sources_complete = len(source_rows) <= 20
    today = date.today()
    day_from = today - timedelta(days=29)
    day_to = today + timedelta(days=1)
    day_rows = await store.distribution_days(
        **common, day_from=day_from.isoformat(), day_to=day_to.isoformat()
    )
    by_day = {str(row["day"]): int(row["n"]) for row in day_rows}
    days = []
    for offset in range(30):
        day = (day_from + timedelta(days=offset)).isoformat()
        days.append({"day": day, "count": by_day.get(day, 0)})
    return SearchDistributionResult(
        total=total,
        sources=[
            {
                "feedUrl": str(row["feed_url"]),
                "feedTitle": str(row["feed_title"]),
                "count": int(row["n"]),
            }
            for row in source_rows[:20]
        ],
        sourcesComplete=sources_complete,
        days=days,
        dayFrom=day_from.isoformat(),
        dayTo=day_to.isoformat(),
    )


# ---------------------------------------------------------------------------
# N141：搜索快照比较 —— 冻结当前结果引用清单，稍后对同一作用域复跑
# 做诚实差分（added / removed / rankChanges / permissionLost）。
# ---------------------------------------------------------------------------

_SNAPSHOT_CAP = 2000
_SNAPSHOT_LIST_CAP = 200
_RANK_CHANGE_THRESHOLD = 5


def _get_search_snapshot_store(request: Request) -> SearchSnapshotStore:
    from lumirss.deps import _cached_on_app_state

    return _cached_on_app_state(
        request,
        "search_snapshot_store",
        lambda: SearchSnapshotStore(request.app.state.db),
    )


def _snapshot_search_params(payload: SearchSnapshotCreate) -> dict[str, Any]:
    """Body → service.search kwargs（与 GET /search 的校验语义一致）。"""
    if payload.feedUrl is not None and payload.categoryId is not None:
        raise SearchQueryError("feedUrl and categoryId are mutually exclusive.")
    if payload.state is not None and payload.state != "unread":
        raise SearchQueryError('state only supports "unread".')
    return {
        "query": payload.q.strip(),
        "feed_url": payload.feedUrl,
        "category_id": payload.categoryId,
        "unread_only": payload.state == "unread",
        "starred_only": bool(payload.favorite),
        "published_from": payload.from_,
        "published_to": payload.to,
        "intitle": payload.intitle,
        "phrase": payload.phrase,
        "exclude": payload.exclude,
        "has_summary": payload.hasSummary,
    }


async def _collect_search_refs(
    request: Request, *, params: dict[str, Any], cap: int
) -> tuple[list[str], bool]:
    """keyset 全量迭代同一过滤链（复用生产查询路径）；返回 (refs, complete)。

    complete=False = 触及 cap 上界被诚实截断（与 F075 同一口径）。"""
    service = _get_search_service(request)
    scope = {
        "q": params["query"],
        "feedUrl": params["feed_url"],
        "categoryId": params["category_id"],
        "unread": params["unread_only"],
        "favorite": params["starred_only"],
        "from": params["published_from"],
        "to": params["published_to"],
        "intitle": params["intitle"],
        "phrase": params["phrase"],
        "exclude": params["exclude"],
        "hasSummary": params["has_summary"],
    }
    refs: list[str] = []
    keyset = None
    complete = True
    for _ in range(9):  # 8 页 × 250 = 2000 上界 + 1 次收尾探测
        result = await service.search(limit=250, keyset=keyset, **params)
        refs.extend(str(row["entryRef"]) for row in result["rows"])
        if not result["hasMore"] or result["nextKeyset"] is None or len(refs) >= cap:
            break
        keyset = decode_search_cursor(
            encode_search_cursor(*result["nextKeyset"], scope=scope), scope=scope
        )
    else:
        complete = False
    if len(refs) > cap:
        refs = refs[:cap]
        complete = False
    return refs, complete


@router.get(
    "/api/v1/search/snapshots",
    response_model=SearchSnapshotList,
    response_model_exclude_none=False,
)
async def list_search_snapshots(request: Request) -> SearchSnapshotList:
    """N141：快照列表（最新优先；引用计数而非引用清单，出站有界）。"""
    store = _get_search_snapshot_store(request)
    rows = await store.list()
    return SearchSnapshotList(
        items=[
            SearchSnapshotView(
                id=row["id"],
                query=row["query"],
                filters=row["filters"],
                refCount=row["refCount"],
                truncated=row["truncated"],
                createdAt=row["createdAt"],
            )
            for row in rows
        ]
    )


@router.post(
    "/api/v1/search/snapshots",
    response_model=SearchSnapshotView,
    status_code=201,
    response_model_exclude_none=False,
)
async def create_search_snapshot(
    payload: SearchSnapshotCreate, request: Request
) -> SearchSnapshotView:
    """N141 冻结：对当前查询+过滤作用域做一次 keyset 全量迭代（≤2000
    条，触界诚实标注 truncated），把引用清单存入 per-user 快照表
    （cap 20，超界自动淘汰最老）。查询为空/非法 → 400。"""
    query = payload.q.strip()
    if not query:
        raise SearchQueryError("Search query is empty.")
    if len(query) > 200:
        raise SearchQueryError("Search query is too long.")

    params = _snapshot_search_params(payload)
    refs, complete = await _collect_search_refs(
        request, params=params, cap=_SNAPSHOT_CAP
    )
    store = _get_search_snapshot_store(request)
    filters_payload = {
        key: value
        for key, value in {
            "feedUrl": payload.feedUrl,
            "categoryId": payload.categoryId,
            "state": payload.state,
            "favorite": bool(payload.favorite) or None,
            "from": payload.from_,
            "to": payload.to,
            "intitle": payload.intitle,
            "phrase": payload.phrase,
            "exclude": payload.exclude,
            "hasSummary": payload.hasSummary,
        }.items()
        if value is not None
    }
    row = await store.create(
        query, filters_payload, refs, truncated=not complete
    )
    return SearchSnapshotView(
        id=row["id"],
        query=row["query"],
        filters=row["filters"],
        refCount=row["refCount"],
        truncated=row["truncated"],
        createdAt=row["createdAt"],
    )


@router.post(
    "/api/v1/search/snapshots/{snapshot_id}/compare",
    response_model=SearchSnapshotCompareResult,
    response_model_exclude_none=False,
)
async def compare_search_snapshot(
    snapshot_id: str, request: Request
) -> SearchSnapshotCompareResult:
    """N141 比较：对快照存储的作用域原样复跑（存什么跑什么，绝不
    重新解释），与冻结清单做差分：

    - added / removed：双向集合差（保持 newest-first 顺序；列表 ≤200
      条，counts 为全量诚实计数）；
    - rankChanges：两侧共同引用按位置排名，|位移| > 5 才列入；
    - permissionLost：removed 中在本账户投影已不再解析的引用——
      per-user 库查不到与 404 同语义，绝不泄露他人条目存在性；
    - 任一侧触界截断 → complete=false。快照缺失 → 404。"""
    store = _get_search_snapshot_store(request)
    snapshot = await store.get(snapshot_id)
    if snapshot is None:
        raise SearchSnapshotNotFound(snapshot_id)

    filters = snapshot.get("filters") or {}
    params: dict[str, Any] = {
        "query": snapshot["query"],
        "feed_url": filters.get("feedUrl"),
        "category_id": filters.get("categoryId"),
        "unread_only": filters.get("state") == "unread",
        "starred_only": bool(filters.get("favorite", False)),
        "published_from": filters.get("from"),
        "published_to": filters.get("to"),
        "intitle": filters.get("intitle"),
        "phrase": filters.get("phrase"),
        "exclude": filters.get("exclude"),
        "has_summary": filters.get("hasSummary"),
    }
    current_refs, complete_current = await _collect_search_refs(
        request, params=params, cap=_SNAPSHOT_CAP
    )
    old_refs = snapshot.get("refs") or []
    complete = complete_current and not snapshot.get("truncated", False)

    old_set = set(old_refs)
    new_set = set(current_refs)
    added_all = [ref for ref in current_refs if ref not in old_set]
    removed_all = [ref for ref in old_refs if ref not in new_set]

    old_rank = {ref: index + 1 for index, ref in enumerate(old_refs)}
    rank_changes_all = [
        SearchSnapshotRankChange(
            entryRef=ref, oldRank=old_rank[ref], newRank=index + 1
        )
        for index, ref in enumerate(current_refs)
        if ref in old_rank and abs(old_rank[ref] - (index + 1)) > _RANK_CHANGE_THRESHOLD
    ]

    # permissionLost：仅对 removed 引用做存在性检查（有界 ≤2000）。
    search_store = _get_search_service(request).store
    resolved = await search_store.entry_refs_existing(removed_all)
    permission_lost_all = [ref for ref in removed_all if ref not in resolved]

    return SearchSnapshotCompareResult(
        added=added_all[:_SNAPSHOT_LIST_CAP],
        removed=removed_all[:_SNAPSHOT_LIST_CAP],
        rankChanges=rank_changes_all[:_SNAPSHOT_LIST_CAP],
        permissionLost=permission_lost_all[:_SNAPSHOT_LIST_CAP],
        counts={
            "snapshot": len(old_set),
            "current": len(new_set),
            "added": len(added_all),
            "removed": len(removed_all),
            "rankChanges": len(rank_changes_all),
            "permissionLost": len(permission_lost_all),
        },
        complete=complete,
    )


# ---------------------------------------------------------------------------
# N149：主题演变时间线 —— 24 个月逐月计数（SQL 聚合，同参同权限）+
# 匹配查询的本人批注（LIKE，≤10 条诚实截断）。
# ---------------------------------------------------------------------------


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


@router.get(
    "/api/v1/search/timeline",
    response_model=SearchTimelineResult,
    response_model_exclude_none=False,
)
async def search_timeline(
    request: Request,
    q: str,
    feedUrl: str | None = None,
    categoryId: str | None = None,
    state: str | None = None,
    favorite: bool | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    intitle: str | None = None,
    phrase: str | None = None,
    exclude: str | None = None,
    hasSummary: bool | None = None,
) -> SearchTimelineResult:
    """N149：与 GET /search 相同的权限与过滤作用域（per-user DB 路由 +
    同一过滤链），24 个月逐月计数在 SQL 完成（GROUP BY 月份前缀）——
    只回每月计数，绝不搬运正文。批注腿只含本人批注（annotations 表在
    per-user 库中），excerpt/note LIKE 匹配查询，≤10 条 + 超界诚实
    标注。同义词扩展不参与（聚合口径 = 基础词条过滤链，与 N145 一致）。"""
    from datetime import date

    from lumirss.annotation_store import AnnotationStore
    from lumirss.search_index import split_terms

    query = q.strip()
    if not query:
        raise SearchQueryError("Search query is empty.")
    if len(query) > 200:
        raise SearchQueryError("Search query is too long.")
    if feedUrl is not None and categoryId is not None:
        raise SearchQueryError(
            "feedUrl and categoryId are mutually exclusive."
        )
    if state is not None and state != "unread":
        raise SearchQueryError('state only supports "unread".')

    store = _get_search_service(request).store
    await store.ensure_migrated()
    common: dict[str, Any] = dict(
        terms=split_terms(query),
        intitle_terms=split_terms(intitle or "")[:2] or None,
        phrase=(phrase or "").strip() or None,
        exclude_terms=split_terms(exclude or "")[:2] or None,
        feed_url=feedUrl,
        category_id=categoryId,
        unread_only=state == "unread",
        starred_only=bool(favorite),
        published_from=from_,
        published_to=to,
        has_summary=hasSummary,
    )
    today = date.today()
    start_year, start_month = _shift_month(today.year, today.month, -23)
    next_year, next_month = _shift_month(today.year, today.month, 1)
    month_from = f"{start_year:04d}-{start_month:02d}"
    month_to = f"{next_year:04d}-{next_month:02d}"
    month_rows = await store.distribution_months(
        **common, month_from=month_from, month_to=month_to
    )
    by_month = {str(row["month"]): int(row["n"]) for row in month_rows}
    months: list[SearchTimelineMonth] = []
    year, month = start_year, start_month
    for _ in range(24):
        key = f"{year:04d}-{month:02d}"
        months.append(SearchTimelineMonth(month=key, count=by_month.get(key, 0)))
        year, month = _shift_month(year, month, 1)
    total = sum(entry.count for entry in months)

    annotation_store = AnnotationStore(request.app.state.db)
    annotations_raw, annotations_complete = await annotation_store.search_bounded(
        query, limit=10
    )
    annotations = [
        SearchTimelineAnnotation(
            id=item["id"],
            entryRef=item["entryRef"],
            excerpt=item["excerpt"],
            note=item["note"],
            color=item["color"],
            createdAt=item["createdAt"],
            updatedAt=item["updatedAt"],
        )
        for item in annotations_raw
    ]
    return SearchTimelineResult(
        months=months,
        monthFrom=month_from,
        monthTo=month_to,
        total=total,
        annotations=annotations,
        annotationsComplete=annotations_complete,
    )

