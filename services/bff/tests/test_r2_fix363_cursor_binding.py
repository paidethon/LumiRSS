"""FIX-363: 分页游标必须绑定其查询（筛选 + 账户指纹）。

缺陷基线：续页 token 只校验「形状合法」，不校验它属于哪个查询/账户——
A 的过滤词 / 他人账户 / 别的工作区铸造的 token 拿到 B 的查询里照样续页，
把另一份结果集静默拼接进当前列表。修复后：token 内绑定发放查询的指纹，
外来源 token → 干净 4xx；本源 token 翻页不受影响。

覆盖六条 keyset 分页面：/entries（账户）、/library/bookmarks（账户+q）、
/library/clips（账户）、/inbox/items（账户+sourceUuid）、工作区 timeline
（工作区）、/search 双腿（scope 携带账户）、/annotations（账户+color+q）。
"""

import asyncio
import base64
import json

import pytest
from fastapi.testclient import TestClient

from lumirss.cursor import encode_cursor, scope_fingerprint
from lumirss.main import app
from lumirss.models import EntryListItem, EntryPage
from lumirss.routers.inbox import _encode_cursor as _encode_inbox_cursor
from lumirss.search_library import encode_library_search_cursor

FOREIGN_ACCOUNT = "account-intruder"


# --- /api/v1/entries — 账户绑定 ----------------------------------------------


def test_entries_cursor_from_another_account_is_rejected():
    """他人账户铸造的 continuation 不得续接本账户查询 → 400。"""
    cursor = encode_cursor("12345", "all", None, account=FOREIGN_ACCOUNT)
    with TestClient(app) as client:
        response = client.get("/api/v1/entries", params={"cursor": cursor})
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_cursor"


def test_entries_cursor_without_account_binding_is_rejected():
    """升级前无账户绑定的旧 token 一律失效（fail closed，重翻第一页）。"""
    cursor = encode_cursor("12345", "all", None, account=None)
    with TestClient(app) as client:
        response = client.get("/api/v1/entries", params={"cursor": cursor})
    assert response.status_code == 400


def test_entries_cursor_from_own_account_still_pages():
    """本账户 token 正常续页（正对照）。"""

    class FakeAdapter:
        async def list_entries(self, *, view="all", feed_url=None, category_id=None,
                               source_type=None, continuation=None):
            return EntryPage(
                items=[EntryListItem(
                    entryRef="e1.abc", title="续页文章",
                    feedTitle="Feed", read=False, starred=False,
                )],
                upstreamContinuation=None,
            )

    with TestClient(app) as client:
        app.state.freshrss_adapter = FakeAdapter()
        try:
            cursor = encode_cursor(
                "12345", "all", None, account=app.state.owner_id
            )
            response = client.get("/api/v1/entries", params={"cursor": cursor})
        finally:
            app.state.freshrss_adapter = None
    assert response.status_code == 200
    assert [item["entryRef"] for item in response.json()["items"]] == ["e1.abc"]


# --- /api/v1/library/bookmarks — 账户 + q 过滤绑定 ----------------------------


def _seed_bookmarks(client, count, title_prefix="游标"):
    refs = []
    for i in range(count):
        body = client.post(
            "/api/v1/library/bookmarks",
            json={"url": f"https://example.com/{title_prefix}-{i}",
                  "title": f"{title_prefix}条目{i}"},
        )
        assert body.status_code == 201, body.text
        refs.append(body.json()["ref"])
    return refs


def test_bookmark_cursor_from_another_filter_is_rejected():
    with TestClient(app) as client:
        _seed_bookmarks(client, 3, title_prefix="阿尔法")
        page1 = client.get(
            "/api/v1/library/bookmarks", params={"q": "阿尔法", "limit": 2}
        ).json()
        assert page1["nextCursor"]
        foreign = client.get(
            "/api/v1/library/bookmarks",
            params={"q": "贝塔", "limit": 2, "cursor": page1["nextCursor"]},
        )
        assert foreign.status_code == 400
        assert foreign.json()["error"]["type"] == "invalid_bookmark"
        unfiltered = client.get(
            "/api/v1/library/bookmarks",
            params={"limit": 2, "cursor": page1["nextCursor"]},
        )
        assert unfiltered.status_code == 400


def test_bookmark_cursor_same_filter_still_pages():
    with TestClient(app) as client:
        _seed_bookmarks(client, 3, title_prefix="伽马")
        page1 = client.get(
            "/api/v1/library/bookmarks", params={"q": "伽马", "limit": 2}
        ).json()
        page2 = client.get(
            "/api/v1/library/bookmarks",
            params={"q": "伽马", "limit": 2, "cursor": page1["nextCursor"]},
        )
        assert page2.status_code == 200
        assert len(page2.json()["items"]) == 1


# --- /api/v1/library/clips — 账户绑定（store 层指纹） -------------------------


def test_clip_cursor_from_another_account_is_rejected(tmp_path):
    from lumirss.library_clips import ClipInvalid, ClipStore
    from lumirss.storage import Database

    async def seed_and_page():
        db = Database(tmp_path / "lumi.sqlite")
        await db.migrate()
        store = ClipStore(db)
        for i in range(3):
            await store.create_clip(
                url=f"https://example.com/clip-{i}",
                title=f"剪藏{i}",
                content_html="<p>正文</p>",
                content_text="正文",
            )
        return store

    store = asyncio.run(seed_and_page())

    def run(coroutine):
        return asyncio.run(coroutine)

    items, next_cursor = run(
        store.list_clips(limit=2, scope_account="alice")
    )
    assert len(items) == 2 and next_cursor

    with pytest.raises(ClipInvalid):
        run(store.list_clips(cursor=next_cursor, limit=2, scope_account="bob"))

    items2, _ = run(store.list_clips(cursor=next_cursor, limit=2, scope_account="alice"))
    assert len(items2) == 1


# --- /api/v1/inbox/items — 账户 + sourceUuid 绑定 -----------------------------


def _mint_inbox_cursor(owner_id: str, source_uuid: str) -> str:
    payload = {
        "k": "2026-09-01T00:00:00+00:00",
        "u": "018f0000-0000-7000-8000-000000000001",
        "s": scope_fingerprint(owner_id, source_uuid),
    }
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return "c1ib." + raw


def test_inbox_cursor_from_another_source_or_account_is_rejected():
    with TestClient(app) as client:
        foreign_source = _mint_inbox_cursor(app.state.owner_id, "src-other")
        response = client.get(
            "/api/v1/inbox/items",
            params={"sourceUuid": "src-mine", "cursor": foreign_source},
        )
        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_cursor"

        foreign_account = _encode_inbox_cursor(
            "2026-09-01T00:00:00+00:00",
            "018f0000-0000-7000-8000-000000000001",
            scope_fingerprint(FOREIGN_ACCOUNT, "src-mine"),
        )
        response = client.get(
            "/api/v1/inbox/items",
            params={"sourceUuid": "src-mine", "cursor": foreign_account},
        )
        assert response.status_code == 400


# --- 工作区 timeline（read-later）— 工作区绑定 --------------------------------


def _timeline_store(tmp_path):
    from lumirss.storage import Database
    from lumirss.workspaces import WorkspaceStore

    async def build():
        db = Database(tmp_path / "lumi.sqlite")
        await db.migrate()
        return WorkspaceStore(db)

    return asyncio.run(build())


def test_timeline_cursor_from_another_workspace_is_rejected(tmp_path):
    from lumirss.workspaces import WorkspaceInvalid

    store = _timeline_store(tmp_path)
    mine = asyncio.run(store.create_workspace("我的工作区")).id
    other = asyncio.run(store.create_workspace("别的工作区")).id
    for i in range(2):
        asyncio.run(
            store.add_item(mine, f"library:018f0000-0000-7000-8000-00000000000{i}")
        )

    items, next_cursor = asyncio.run(
        store.list_items_desc(mine, limit=1)
    )
    assert len(items) == 1 and next_cursor

    with pytest.raises(WorkspaceInvalid):
        asyncio.run(store.list_items_desc(other, cursor=next_cursor, limit=1))

    same = asyncio.run(store.list_items_desc(mine, cursor=next_cursor, limit=1))
    assert len(same[0]) == 1


def test_timeline_legacy_cursor_without_workspace_binding_is_rejected(tmp_path):
    """旧格式（未绑定工作区）token fail closed，失效即重翻。"""
    from lumirss.opaque_ref import encode_opaque_ref
    from lumirss.workspaces import RESERVED_WORKSPACE_ID, WorkspaceInvalid

    store = _timeline_store(tmp_path)
    for i in range(2):
        asyncio.run(
            store.add_item(
                RESERVED_WORKSPACE_ID,
                f"library:018f0000-0000-7000-8000-00000000000{i}",
            )
        )
    legacy = encode_opaque_ref(
        "c1ws.",
        json.dumps(
            ["2026-09-01T00:00:00+00:00",
             "library:018f0000-0000-7000-8000-000000000000", "newest"]
        ),
    )
    with pytest.raises(WorkspaceInvalid):
        asyncio.run(
            store.list_items_desc(
                RESERVED_WORKSPACE_ID, cursor=legacy, limit=1
            )
        )


# --- /api/v1/search — 双腿 scope 携带账户 -------------------------------------


def test_search_library_cursor_from_another_account_is_rejected():
    foreign = encode_library_search_cursor(
        "2026-09-01T00:00:00+00:00",
        "library:018f0000-0000-7000-8000-000000000001",
        scope={"q": "检索", "favorite": False, "account": FOREIGN_ACCOUNT},
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/search", params={"q": "检索", "libraryCursor": foreign}
        )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_cursor"


def test_search_library_cursor_from_own_account_is_accepted():
    with TestClient(app) as client:
        own = encode_library_search_cursor(
            "2026-09-01T00:00:00+00:00",
            "library:018f0000-0000-7000-8000-000000000001",
            scope={"q": "检索", "favorite": False,
                   "account": app.state.owner_id},
        )
        response = client.get(
            "/api/v1/search", params={"q": "检索", "libraryCursor": own}
        )
    assert response.status_code == 200, response.text


# --- /api/v1/annotations — 账户 + color + q 绑定 ------------------------------


def _seed_annotations(client, count, color="yellow"):
    from lumirss.annotation_store import AnnotationStore

    async def seed():
        store = AnnotationStore(app.state.db)
        for i in range(count):
            await store.create(
                entry_ref=f"entry-{i % 3}",
                anchor={"block": f"b{i}"},
                excerpt=f"批注摘录{i}",
                note=None,
                color=color,
            )

    asyncio.run(seed())


def test_annotation_cursor_from_another_filter_is_rejected(client):
    _seed_annotations(client, 51, color="yellow")
    page1 = client.get("/api/v1/annotations", params={"color": "yellow"}).json()
    assert page1["nextCursor"], "需要超过一页的批注才能铸造续页 token"

    cross_color = client.get(
        "/api/v1/annotations",
        params={"color": "blue", "cursor": page1["nextCursor"]},
    )
    assert cross_color.status_code == 422
    assert cross_color.json()["error"]["type"] == "invalid_annotation"

    unfiltered = client.get(
        "/api/v1/annotations", params={"cursor": page1["nextCursor"]}
    )
    assert unfiltered.status_code == 422

    legacy_two_part = page1["nextCursor"].split("|", 1)
    legacy = f"{legacy_two_part[0]}|{legacy_two_part[1]}"
    legacy_response = client.get(
        "/api/v1/annotations", params={"cursor": legacy}
    )
    assert legacy_response.status_code == 422


def test_annotation_cursor_same_filter_still_pages(client):
    _seed_annotations(client, 51, color="yellow")
    page1 = client.get("/api/v1/annotations", params={"color": "yellow"}).json()
    page2 = client.get(
        "/api/v1/annotations",
        params={"color": "yellow", "cursor": page1["nextCursor"]},
    )
    assert page2.status_code == 200
    assert len(page2.json()["items"]) == 1
    assert page2.json()["nextCursor"] is None
