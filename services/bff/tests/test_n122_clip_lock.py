"""N122 剪藏版本锁定 — locked 旗标 + 刷新候选。

锁定时 refresh 只落候选（展示版本绝不动）；对展示内容的覆盖式写入
（PATCH revision / 应用候选）→ 409 clip_locked；解锁（显式 PUT）后
refresh 直接应用（走 F089 修订槽，原始 content_html 永不覆盖）；
候选 ≠ 已应用（candidate 列与 revised 列互不影响）。
"""

import asyncio

import lumirss.clip_intake as clip_intake_module
from lumirss.clip_fetch import ExtractedPage
from lumirss.library_clips import ClipStore
from lumirss.main import app

HTML_V1 = "<p>版本一正文</p><p>第二段</p>"


def run(coro):
    return asyncio.run(coro)


def _seed(url="https://refresh.example/a", html=HTML_V1, title="可刷新剪辑"):
    async def _inner():
        store = ClipStore(app.state.db)
        view, created = await store.create_clip(
            url=url,
            title=title,
            content_html=html,
            content_text="版本一正文 第二段",
        )
        return view

    view = run(_inner())
    return view.ref.split(":", 1)[1]


def _fake_fetch(html: str, title: str = "新标题", text: str | None = None):
    async def _inner(url, **kwargs):
        return ExtractedPage(
            url=url,
            final_url=url,
            title=title,
            byline=None,
            content_html=html,
            content_text=text or html,
        )

    return _inner


def test_refresh_locked_stores_candidate_only(client, monkeypatch):
    """锁定 → refresh 只存候选：展示版本与原始版本都不变。"""
    uuid = _seed()
    locked = client.put(
        f"/api/v1/library/clips/{uuid}/lock", json={"locked": True}
    )
    assert locked.status_code == 200
    assert locked.json()["locked"] is True

    monkeypatch.setattr(
        clip_intake_module,
        "fetch_extract_sanitize",
        _fake_fetch("<p>版本二全新内容</p>", title="版本二标题"),
    )
    refreshed = client.post(f"/api/v1/library/clips/{uuid}/refresh")
    assert refreshed.status_code == 200, refreshed.text
    body = refreshed.json()
    assert body["status"] == "candidate"
    assert body["locked"] is True

    detail = client.get(f"/api/v1/library/clips/{uuid}/full").json()
    # 展示版本不动
    assert "版本一正文" in detail["content"]["html"]
    assert "版本二" not in detail["content"]["html"]
    # 原始版本不动
    assert "版本一正文" in detail["original"]["html"]
    # 候选就位且 ≠ 已应用
    assert detail["locked"] is True
    assert detail["candidate"] is not None
    assert "版本二" in detail["candidate"]["title"]
    assert detail["revised"] is None

    # 候选可查看（零写入）
    candidate = client.get(f"/api/v1/library/clips/{uuid}/candidate").json()
    assert "版本二全新内容" in candidate["contentHtml"]


def test_locked_clip_rejects_overwrite_writes(client):
    """锁定时 PATCH revision / 应用候选 → 409 clip_locked。"""
    uuid = _seed()
    client.put(f"/api/v1/library/clips/{uuid}/lock", json={"locked": True})

    revision = client.patch(
        f"/api/v1/library/clips/{uuid}/revision",
        json={"blocks": ["b0"], "note": "试图覆盖"},
    )
    assert revision.status_code == 409
    assert revision.json()["error"]["type"] == "clip_locked"

    apply_attempt = client.post(f"/api/v1/library/clips/{uuid}/candidate/apply")
    # 无候选也必须先撞锁（不泄露候选状态，锁定语义优先）
    assert apply_attempt.status_code == 409
    assert apply_attempt.json()["error"]["type"] == "clip_locked"

    # 解锁后同样的修订放行
    client.put(f"/api/v1/library/clips/{uuid}/lock", json={"locked": False})
    ok = client.patch(
        f"/api/v1/library/clips/{uuid}/revision",
        json={"blocks": ["b0"], "note": "解锁后修订"},
    )
    assert ok.status_code == 200


def test_unlock_then_refresh_applies_via_revision_slot(client, monkeypatch):
    """解锁 → refresh 直接应用：写入修订槽（原始 content_html 不变）。"""
    uuid = _seed()
    monkeypatch.setattr(
        clip_intake_module,
        "fetch_extract_sanitize",
        _fake_fetch("<p>版本二已应用内容</p>", title="版本二标题"),
    )
    applied = client.post(f"/api/v1/library/clips/{uuid}/refresh")
    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"

    detail = client.get(f"/api/v1/library/clips/{uuid}/full").json()
    assert "版本二已应用内容" in detail["content"]["html"]
    assert "版本一正文" in detail["original"]["html"]  # 原始永不覆盖
    assert detail["revised"] is not None
    assert detail["candidate"] is None

    # 搜索投影更新为应用后文本
    row = run(
        app.state.db.fetch_one(
            "SELECT body FROM search_library WHERE ref = ?",
            (f"library:{uuid}",),
        )
    )
    assert "版本二" in row["body"]


def test_refresh_unchanged_reports_honestly(client, monkeypatch):
    uuid = _seed()
    monkeypatch.setattr(
        clip_intake_module,
        "fetch_extract_sanitize",
        _fake_fetch(HTML_V1, title="可刷新剪辑"),
    )
    refreshed = client.post(f"/api/v1/library/clips/{uuid}/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["status"] == "unchanged"
    detail = client.get(f"/api/v1/library/clips/{uuid}/full").json()
    assert detail["candidate"] is None


def test_candidate_apply_with_keep_ids_sanitized(client, monkeypatch):
    """候选 + keepIds 应用：同一净化管线（script 绝不入库）+ 原始不动。"""
    uuid = _seed()
    client.put(f"/api/v1/library/clips/{uuid}/lock", json={"locked": True})
    dirty = "<p>干净段落</p><p>噪声段落</p><script>alert(1)</script>"
    monkeypatch.setattr(
        clip_intake_module, "fetch_extract_sanitize", _fake_fetch(dirty)
    )
    refreshed = client.post(f"/api/v1/library/clips/{uuid}/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["status"] == "candidate"

    # 锁定中不能应用
    blocked = client.post(
        f"/api/v1/library/clips/{uuid}/candidate/apply",
        json={"keepIds": ["b0"]},
    )
    assert blocked.status_code == 409

    client.put(f"/api/v1/library/clips/{uuid}/lock", json={"locked": False})
    applied = client.post(
        f"/api/v1/library/clips/{uuid}/candidate/apply",
        json={"keepIds": ["b0"]},
    )
    assert applied.status_code == 200, applied.text
    detail = client.get(f"/api/v1/library/clips/{uuid}/full").json()
    assert "干净段落" in detail["content"]["html"]
    assert "噪声段落" not in detail["content"]["html"]
    assert "<script" not in detail["content"]["html"].lower()
    assert "alert(1)" not in detail["content"]["html"]
    assert "版本一正文" in detail["original"]["html"]
    # 候选槽已清空（≠ 已应用：内容进了修订槽）
    assert detail["candidate"] is None
    assert detail["revised"] is not None


def test_discard_candidate_and_missing_candidate_404(client, monkeypatch):
    uuid = _seed()
    missing = client.delete(f"/api/v1/library/clips/{uuid}/candidate")
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "clip_candidate_not_found"

    client.put(f"/api/v1/library/clips/{uuid}/lock", json={"locked": True})
    monkeypatch.setattr(
        clip_intake_module,
        "fetch_extract_sanitize",
        _fake_fetch("<p>候选内容</p>"),
    )
    client.post(f"/api/v1/library/clips/{uuid}/refresh")
    discarded = client.delete(f"/api/v1/library/clips/{uuid}/candidate")
    assert discarded.status_code == 204
    detail = client.get(f"/api/v1/library/clips/{uuid}/full").json()
    assert detail["candidate"] is None
    assert "版本一正文" in detail["content"]["html"]


def test_lock_toggle_roundtrip_and_missing_clip(client):
    missing = client.put(
        "/api/v1/library/clips/no-such-uuid/lock", json={"locked": True}
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "clip_not_found"

    uuid = _seed()
    on = client.put(f"/api/v1/library/clips/{uuid}/lock", json={"locked": True})
    assert on.json()["locked"] is True
    off = client.put(f"/api/v1/library/clips/{uuid}/lock", json={"locked": False})
    assert off.json()["locked"] is False
