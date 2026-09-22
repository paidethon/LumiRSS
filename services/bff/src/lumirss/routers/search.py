"""Global search routes (0022).

GET /api/v1/search — one page of hits over the derived projection.
POST /api/v1/search/rebuild — explicit bounded rebuild (admin op).

Every parameter is validated here; the projection query itself is a
single static statement (see search_store.py). Snippets are plain text
extracted from the sanitized content text — the web client renders
them as text, never as HTML.
"""

import time
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from lumirss.models import (
    SavedSearchCount,
    SavedSearchCreate,
    SavedSearchList,
    SavedSearchPinOrder,
    SavedSearchRename,
    SavedSearchView,
    SearchRebuildResult,
    SearchResponse,
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


def _saved_model(row: dict[str, Any]) -> SavedSearchView:
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
        createdAt=row["createdAt"],
        updatedAt=row["updatedAt"],
    )


@router.get("/api/v1/search/views", response_model=SavedSearchList)
async def list_saved_search_views(request: Request) -> SavedSearchList:
    store = _get_saved_search_store(request)
    rows = await store.list()
    return SavedSearchList(items=[_saved_model(row) for row in rows])


@router.post(
    "/api/v1/search/views", response_model=SavedSearchView, status_code=201
)
async def create_saved_search_view(
    payload: SavedSearchCreate, request: Request
) -> SavedSearchView:
    """Save the current query + filter intent (not the result set)."""
    store = _get_saved_search_store(request)
    row = await store.create(
        payload.name, payload.query,
        {"view": payload.view, "categoryKey": payload.categoryKey},
    )
    if payload.filters is not None:
        from lumirss.saved_search_store import normalize_filters

        row = await store.set_filters(row["id"], normalize_filters(payload.filters))
    return _saved_model(row)


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
    return _saved_model(row)


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
    return SavedSearchList(items=[_saved_model(row) for row in rows])


@router.post("/api/v1/search/views/{view_id}/pin", response_model=SavedSearchView)
async def pin_saved_search_view(view_id: str, request: Request) -> SavedSearchView:
    store = _get_saved_search_store(request)
    row = await store.set_pinned(view_id, True)
    if row is None:
        raise SavedSearchNotFound(view_id)
    return _saved_model(row)


@router.post("/api/v1/search/views/{view_id}/unpin", response_model=SavedSearchView)
async def unpin_saved_search_view(view_id: str, request: Request) -> SavedSearchView:
    store = _get_saved_search_store(request)
    row = await store.set_pinned(view_id, False)
    if row is None:
        raise SavedSearchNotFound(view_id)
    return _saved_model(row)


@router.patch("/api/v1/search/views/{view_id}/pin-order", response_model=SavedSearchView)
async def reorder_pinned_view(
    view_id: str, payload: SavedSearchPinOrder, request: Request
) -> SavedSearchView:
    store = _get_saved_search_store(request)
    row = await store.set_pin_order(view_id, payload.pinOrder)
    if row is None:
        raise SavedSearchNotFound(view_id)
    return _saved_model(row)


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
