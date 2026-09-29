"""NEW-244 链接存活复核 — 批量有界检查 + 四档诚实结果 + 隔离。

- 注入假 LinkCheckService（本模块命名空间打桩）验证四档映射：
  ok / redirect（报 finalUrl）/ dead（404、410）/ unknown（超时等）；
- 解析失败也诚实：未知书签 / 投影缺失 / 无 URL → unknown + detail；
- 校验：空 refs、超过 50 条 → 422；
- 隔离：A 的复核台账对 B 不可见（真实 RoutingDatabase per-user 库）。
"""

import asyncio

import lumirss.new244_link_recheck as recheck_module
from lumirss.entryref import encode_entry_ref
from new231_helpers import ab_session


class FakeChecker:
    """按 URL 返回预设探测结果（不发起任何网络请求）。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def check_many(self, urls: list[str]) -> list[dict]:
        return [self._table()[url] for url in urls]

    @staticmethod
    def _table() -> dict[str, dict]:
        return {
            "https://ok.example/a": {"ref": "https://ok.example/a", "status": "ok", "http_status": 200, "final_url": None},
            "https://moved.example/old": {"ref": "https://moved.example/old", "status": "redirect", "http_status": 301, "final_url": "https://moved.example/new"},
            "https://gone.example/404": {"ref": "https://gone.example/404", "status": "not_found", "http_status": 404, "final_url": None},
            "https://slow.example/x": {"ref": "https://slow.example/x", "status": "timeout", "http_status": None, "final_url": None},
        }


def _seed_bookmark(client, item_uuid: str, url: str) -> str:
    async def _seed():
        await client.app.state.db.migrate()
        await client.app.state.db.execute(
            "INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'bookmark', '2026-09-01T00:00:00+00:00')",
            (item_uuid,),
        )
        await client.app.state.db.execute(
            "INSERT INTO library_bookmarks (item_uuid, item_type, url, title, note, created_at) VALUES (?, 'url', ?, '书签', '', '2026-09-01T00:00:00+00:00')",
            (item_uuid, url),
        )

    asyncio.run(_seed())
    return f"library:{item_uuid}"


def _seed_rss(client, item_id: str, url: str) -> str:
    entry_ref = encode_entry_ref(item_id)

    async def _seed():
        await client.app.state.db.migrate()
        await client.app.state.db.execute(
            "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) "
            "VALUES (?, ?, 'https://f.example/rss', '源', '文章', '', ?, '', '2026-09-01T00:00:00+00:00', 0, 0, 0)",
            (item_id, entry_ref, url),
        )

    asyncio.run(_seed())
    return f"rss:{entry_ref}"


def test_new244_four_honest_categories(client, monkeypatch):
    """ok / redirect（finalUrl）/ dead / unknown 四档；解析失败也 unknown+detail。"""
    monkeypatch.setattr(recheck_module, "LinkCheckService", FakeChecker)
    ref_ok = _seed_bookmark(client, "11111111-1111-4111-8111-111111111111", "https://ok.example/a")
    ref_moved = _seed_bookmark(client, "22222222-2222-4222-8222-222222222222", "https://moved.example/old")
    ref_dead = _seed_rss(client, "dead-1", "https://gone.example/404")
    ref_slow = _seed_rss(client, "slow-1", "https://slow.example/x")
    ref_missing = "library:99999999-9999-4999-8999-999999999999"
    ref_noprojection = "rss:" + encode_entry_ref("ghost")

    run = client.post(
        "/api/v1/library/link-recheck",
        json={"refs": [ref_ok, ref_moved, ref_dead, ref_slow, ref_missing, ref_noprojection]},
    )
    assert run.status_code == 200, run.text
    by_ref = {item["ref"]: item for item in run.json()["items"]}
    assert by_ref[ref_ok]["status"] == "ok"
    assert by_ref[ref_moved]["status"] == "redirect"
    assert by_ref[ref_moved]["finalUrl"] == "https://moved.example/new"
    assert by_ref[ref_dead]["status"] == "dead"
    assert by_ref[ref_dead]["httpStatus"] == 404
    assert by_ref[ref_slow]["status"] == "unknown"
    assert by_ref[ref_missing]["status"] == "unknown"
    assert by_ref[ref_missing]["detail"] == "bookmark_missing"
    assert by_ref[ref_noprojection]["status"] == "unknown"
    assert by_ref[ref_noprojection]["detail"] == "projection_missing"

    # 台账：结果逐条落库，GET results 可回看
    results = client.get("/api/v1/library/link-recheck/results")
    assert results.status_code == 200
    assert len(results.json()["items"]) == 6


def test_new244_validation(client):
    empty = client.post("/api/v1/library/link-recheck", json={"refs": []})
    assert empty.status_code == 422

    # >50 条：pydantic 层拒绝（422 invalid_request）
    too_many = client.post(
        "/api/v1/library/link-recheck", json={"refs": [f"library:{i:04d}" for i in range(51)]}
    )
    assert too_many.status_code == 422

    # ref 形制非法：到得了 store 层 → 422 link_recheck_invalid（诚实拒绝）
    bad_ref = client.post("/api/v1/library/link-recheck", json={"refs": ["x" * 501]})
    assert bad_ref.status_code == 422
    assert bad_ref.json()["error"]["type"] == "link_recheck_invalid"

    # 结构未知但形制合法：不猜 → unknown + bad_ref（不 4xx 拒绝）
    weird = client.post("/api/v1/library/link-recheck", json={"refs": ["not-a-ref"]})
    assert weird.status_code == 200
    assert weird.json()["items"][0]["status"] == "unknown"
    assert weird.json()["items"][0]["detail"] == "bad_ref"


def test_new244_isolation_between_users(monkeypatch, tmp_path):
    """A 的复核台账对 B 不可见（真实 RoutingDatabase per-user 库）。"""
    monkeypatch.setattr(recheck_module, "LinkCheckService", FakeChecker)
    with ab_session(monkeypatch, tmp_path) as session:
        member = session.activate_member("n24x-b")
        run = session.client.post(
            "/api/v1/library/link-recheck",
            json={"refs": ["library:88888888-8888-4888-8888-888888888888"]},
            headers=session.owner,
        )
        assert run.status_code == 200, run.text

        b_results = session.client.get(
            "/api/v1/library/link-recheck/results", headers=member
        )
        assert b_results.status_code == 200
        assert b_results.json()["items"] == []

        a_results = session.client.get(
            "/api/v1/library/link-recheck/results", headers=session.owner
        )
        assert len(a_results.json()["items"]) == 1
