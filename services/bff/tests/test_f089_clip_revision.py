"""F089 剪藏手工修订 — 原始版本不可变（负向）、全删 422/force、修订后
搜索命中新文本、恢复原始、XSS 净化、并发修订 409 base mismatch。"""

import asyncio

from lumirss.library_clips import ClipStore
from lumirss.main import app

UUID = "00000000-0000-4000-8000-0000000009c1"
HTML = "<p>alpha block</p><p>beta block</p><p>gamma block</p>"


def run(coro):
    return asyncio.run(coro)


def _seed(client):
    async def _seed_inner():
        store = ClipStore(app.state.db)
        view, created = await store.create_clip(
            url="https://clip.example/rev",
            title="修订剪辑",
            content_html=HTML,
            content_text="alpha block beta block gamma block",
        )
        await app.state.db.migrate()
        return view

    view = run(_seed_inner())
    return view.ref.split(":", 1)[1]


def test_f089_revision_keeps_original_immutable(client):
    uuid = _seed(client)
    blocks = client.get(f"/api/v1/library/clips/{uuid}/revision").json()["blocks"]
    assert [b["id"] for b in blocks] == ["b0", "b1", "b2"]
    # 只保留 b0 与 b2，附整理说明
    saved = client.patch(
        f"/api/v1/library/clips/{uuid}/revision",
        json={"blocks": ["b0", "b2"], "note": "去掉广告段"},
    )
    assert saved.status_code == 200, saved.text
    detail = client.get(f"/api/v1/library/clips/{uuid}/full").json()
    assert "alpha block" in detail["content"]["html"]
    assert "beta block" not in detail["content"]["html"]
    # 负向：原始版本不可变
    assert detail["original"]["html"] == HTML
    assert detail["revised"]["note"] == "去掉广告段"
    # 搜索投影更新为修订后文本（原版不入索引）
    row = run(
        app.state.db.fetch_one(
            "SELECT body FROM search_library WHERE ref = ?", (f"library:{uuid}",)
        )
    )
    assert "alpha" in row["body"] and "beta" not in row["body"]


def test_f089_must_keep_one_and_force_and_restore(client):
    uuid = _seed(client)
    empty = client.patch(
        f"/api/v1/library/clips/{uuid}/revision", json={"blocks": []}
    )
    assert empty.status_code == 422
    assert empty.json()["error"]["type"] == "must_keep_one"
    forced = client.patch(
        f"/api/v1/library/clips/{uuid}/revision",
        json={"blocks": [], "force": True, "note": "清空重写"},
    )
    assert forced.status_code == 200, forced.text
    detail = client.get(f"/api/v1/library/clips/{uuid}/full").json()
    assert detail["content"]["html"] == ""
    assert detail["original"]["html"] == HTML  # 原始仍完整保留
    # 恢复原始（删修订）
    restored = client.delete(f"/api/v1/library/clips/{uuid}/revision")
    assert restored.status_code == 204
    detail2 = client.get(f"/api/v1/library/clips/{uuid}/full").json()
    assert detail2["content"]["html"] == HTML
    assert detail2["revised"] is None


def test_f089_search_hits_revised_not_original(client):
    uuid = _seed(client)
    client.patch(
        f"/api/v1/library/clips/{uuid}/revision",
        json={"blocks": ["b1"], "note": None},
    )
    row = run(
        app.state.db.fetch_one(
            "SELECT body FROM search_library WHERE ref = ?", (f"library:{uuid}",)
        )
    )
    assert "beta" in row["body"]
    assert "alpha" not in row["body"] and "gamma" not in row["body"]


def test_f089_xss_sanitized_in_revision(client):
    uuid = _seed(client)
    # 注入：伪造带 script 的修订内容走同一条服务端重组+净化路径
    # 直接改底稿（模拟上游脏数据）后经修订入口重组净化
    async def _dirty():
        await app.state.db.execute(
            "UPDATE library_clips SET content_html = ? WHERE item_uuid = ?",
            ("<p>safe</p><p>x</p><script>alert(1)</script><p onclick='h'>end</p>", UUID),
        )
    run(_dirty())
    saved = client.patch(
        f"/api/v1/library/clips/{uuid}/revision",
        json={"blocks": ["b0", "b2", "b3"], "note": None},
    )
    assert saved.status_code == 200, saved.text
    detail = client.get(f"/api/v1/library/clips/{uuid}/full").json()
    assert "<script" not in detail["content"]["html"].lower()
    assert "onclick" not in detail["content"]["html"].lower()
    assert "alert(1)" not in detail["content"]["html"]


def test_f089_concurrent_revision_base_mismatch_409(client):
    uuid = _seed(client)
    base = client.get(f"/api/v1/library/clips/{uuid}/revision").json()
    first = client.patch(
        f"/api/v1/library/clips/{uuid}/revision",
        json={"blocks": ["b0", "b1"], "baseContentHash": base["baseContentHash"]},
    )
    assert first.status_code == 200
    # 并发修订：stale base → 409 base_mismatch
    stale = client.patch(
        f"/api/v1/library/clips/{uuid}/revision",
        json={"blocks": ["b2"], "baseContentHash": base["baseContentHash"]},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["type"] == "base_mismatch"
