"""N020 来源关注级别 —— 覆盖设置、时间线服务端过滤、队列排序。

- PUT /sources/overrides 设置 attentionLevel（must_read|normal|low，
  非法 → 422；normal/None = 清除回默认）；
- GET /entries?attention=must_read|excl_low 服务端过滤（只作用通用
  时间线）：must_read = 只留能肯定解析到 must_read 来源的条目；
  excl_low = 只剔能肯定解析到 low 来源的条目（未知 ≠ low）；
- 今日队列 generate：候选排序 must_read → normal → low（同级内仍按
  近期）；levels 参数限定候选池；未设置级别的来源行为不变；
- 其他用户不受影响（per-user 库隔离由 0005 保证，本套件覆盖级别
  默认语义不改变既有无覆盖行为）。
"""

import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.storage import Database

FEED_A = "https://mustread.example/rss"
FEED_B = "https://low.example/rss"
FEED_C = "https://normal.example/rss"


def run(coroutine):
    return asyncio.run(coroutine)


def _entry(entry_ref: str, feed_url: str):
    from lumirss.adapters.freshrss import EntryListItem

    return EntryListItem(
        entryRef=entry_ref,
        title=f"T {entry_ref}",
        feedTitle=feed_url,
        author=None,
        url=None,
        publishedAt="2026-09-20T00:00:00Z",
        read=False,
        starred=False,
    )


def _install_adapter(entries):
    async def _list_entries(*, view="all", feed_url=None, category_id=None, source_type=None, continuation=None):
        return SimpleNamespace(items=list(entries), upstreamContinuation=None)

    app.state.freshrss_adapter = SimpleNamespace(list_entries=_list_entries)


def _seed_projection(db: Database, triples):
    for ref, feed_url, published_at in triples:
        run(
            db.execute(
                "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ref, ref, feed_url, "源", ref, "", "", "正文", published_at, 0, 0, 1789660000),
            )
        )


def test_n020_override_set_and_invalid_value_rejected(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        put = client.put(
            "/api/v1/sources/overrides",
            json={"feedUrl": FEED_A, "attentionLevel": "must_read"},
        )
        assert put.status_code == 200
        assert put.json()["attentionLevel"] == "must_read"

        low = client.put(
            "/api/v1/sources/overrides",
            json={"feedUrl": FEED_B, "attentionLevel": "low"},
        )
        assert low.json()["attentionLevel"] == "low"

        bad = client.put(
            "/api/v1/sources/overrides",
            json={"feedUrl": FEED_A, "attentionLevel": "urgent"},
        )
        assert bad.status_code == 422

        # normal 与 None 都是清除回默认。
        cleared = client.put(
            "/api/v1/sources/overrides",
            json={"feedUrl": FEED_B, "attentionLevel": "normal"},
        )
        assert cleared.json()["attentionLevel"] == "normal"

        # 列表端点带出级别。
        listed = client.get("/api/v1/sources/overrides")
        levels = {
            item["feedUrl"]: item["attentionLevel"] for item in listed.json()["items"]
        }
        assert levels[FEED_A] == "must_read"


def _timeline_scenario(client, tmp_path):
    app.state.db = Database(tmp_path / "lumi.sqlite")
    run(app.state.db.migrate())
    _seed_projection(
        app.state.db,
        [
            ("ref-a", FEED_A, "2026-09-20T00:00:00Z"),
            ("ref-b", FEED_B, "2026-09-20T00:00:00Z"),
            ("ref-c", FEED_C, "2026-09-20T00:00:00Z"),
        ],
    )
    for feed_url, level in ((FEED_A, "must_read"), (FEED_B, "low")):
        client.put(
            "/api/v1/sources/overrides",
            json={"feedUrl": feed_url, "attentionLevel": level},
        )
    _install_adapter(
        [_entry("ref-a", FEED_A), _entry("ref-b", FEED_B), _entry("ref-c", FEED_C)]
    )


def test_n020_timeline_attention_filters(tmp_path):
    with TestClient(app) as client:
        _timeline_scenario(client, tmp_path)
        try:
            # 默认（无参数）不变：全部条目都在。
            default_page = client.get(
                "/api/v1/entries", params={"view": "all"}
            ).json()
            assert {item["entryRef"] for item in default_page["items"]} == {
                "ref-a",
                "ref-b",
                "ref-c",
            }

            # must_read：只留能肯定解析到必读来源的条目。
            must = client.get(
                "/api/v1/entries", params={"view": "all", "attention": "must_read"}
            ).json()
            assert {item["entryRef"] for item in must["items"]} == {"ref-a"}

            # excl_low：剔除低优先来源，其余（含未设置级别的）保留。
            excl = client.get(
                "/api/v1/entries", params={"view": "all", "attention": "excl_low"}
            ).json()
            assert {item["entryRef"] for item in excl["items"]} == {"ref-a", "ref-c"}

            # 非法 mode → FastAPI 校验 422。
            bad = client.get(
                "/api/v1/entries", params={"view": "all", "attention": "yolo"}
            )
            assert bad.status_code == 422
        finally:
            app.state.freshrss_adapter = None


def test_n020_queue_generate_orders_by_attention_level(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        run(app.state.db.migrate())
        # 时间戳刻意让 recency 与级别排序相反：low 最新，must_read 最旧。
        _seed_projection(
            app.state.db,
            [
                ("ref-low-1", FEED_B, "2026-09-24T00:00:00Z"),
                ("ref-low-2", FEED_B, "2026-09-23T00:00:00Z"),
                ("ref-norm", FEED_C, "2026-09-22T00:00:00Z"),
                ("ref-must", FEED_A, "2026-09-21T00:00:00Z"),
            ],
        )
        for feed_url, level in ((FEED_A, "must_read"), (FEED_B, "low")):
            client.put(
                "/api/v1/sources/overrides",
                json={"feedUrl": feed_url, "attentionLevel": level},
            )
        generated = client.post(
            "/api/v1/queue/today/generate", json={}, params={"force": "true"}
        )
        assert generated.status_code == 201
        refs = [item["itemRef"] for item in generated.json()["items"]]
        # must_read 优先 → normal 次之 → low 垫后（同级内仍按近期）。
        assert refs == ["rss:ref-must", "rss:ref-norm", "rss:ref-low-1", "rss:ref-low-2"]

        # levels 限定候选池（normal = 未设置级别）。
        filtered = client.post(
            "/api/v1/queue/today/generate",
            json={"levels": ["must_read"]},
            params={"force": "true"},
        )
        assert filtered.status_code == 201
        refs = [item["itemRef"] for item in filtered.json()["items"]]
        assert refs == ["rss:ref-must"]
        assert "levels=must_read" in filtered.json()["notes"][0]


def test_n020_queue_default_semantics_unchanged_without_overrides(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        run(app.state.db.migrate())
        _seed_projection(
            app.state.db,
            [
                ("ref-1", FEED_C, "2026-09-24T00:00:00Z"),
                ("ref-2", FEED_C, "2026-09-23T00:00:00Z"),
            ],
        )
        _install_adapter([])
        try:
            generated = client.post("/api/v1/queue/today/generate", json={})
            assert generated.status_code == 201
            refs = [item["itemRef"] for item in generated.json()["items"]]
            assert refs == ["rss:ref-1", "rss:ref-2"]
        finally:
            app.state.freshrss_adapter = None
