"""N123 剪藏清理预览 — POST /library/clips/preview-cleanup。

分类健全性（导航/链接列表/广告 → 建议移除；标题/段落/图片 → 保留）、
确认后的保存走既有的净化写入（PATCH revision，同一 sanitize_html）、
确认前绝不改动任何存储内容（原始与展示版本不变）。
"""

import asyncio

from lumirss.library_clips import ClipStore
from lumirss.main import app

PAGE_HTML = (
    "<h1>文章标题</h1>"
    "<p>这是导语段落，说明文章主题，内容足够长，应当保留。</p>"
    '<p><a href="/home">首页</a> <a href="/cat">目录</a> <a href="/prev">上一篇</a>'
    ' <a href="/next">下一篇</a> <a href="/rel">相关阅读</a></p>'
    "<p>广告：限时特惠，点击购买立减。</p>"
    '<p><img src="https://img.example/chart.png" alt="图表"></p>'
    "<p>结论段落：综上所述，观点成立。</p>"
)


def run(coro):
    return asyncio.run(coro)


def _seed():
    async def _inner():
        store = ClipStore(app.state.db)
        view, _created = await store.create_clip(
            url="https://cleanup.example/a",
            title="清理预览剪辑",
            content_html=PAGE_HTML,
            content_text="标题 导语 导航 广告 结论",
        )
        return view

    view = run(_inner())
    return view.ref.split(":", 1)[1]


def test_preview_classification_sanity(client):
    _seed()
    response = client.post(
        "/api/v1/library/clips/preview-cleanup",
        json={"html": PAGE_HTML},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    blocks = body["blocks"]
    by_reason = {b["reason"]: b for b in blocks}
    # 导航/链接列表/广告 → 建议移除
    assert by_reason["link_list"]["keep"] is False
    assert by_reason["ad"]["keep"] is False
    # 标题/段落/图片 → 保留
    assert by_reason["heading"]["keep"] is True
    assert by_reason["paragraph"]["keep"] is True
    assert by_reason["image"]["keep"] is True
    assert body["totalCount"] == len(blocks)
    assert body["keepCount"] == sum(1 for b in blocks if b["keep"])


def test_preview_is_zero_write(client):
    """预览零写入：确认前原始与展示版本都保持原样。"""
    uuid = _seed()
    before = client.get(f"/api/v1/library/clips/{uuid}/full").json()
    client.post("/api/v1/library/clips/preview-cleanup", json={"html": PAGE_HTML})
    after = client.get(f"/api/v1/library/clips/{uuid}/full").json()
    assert before == after
    assert after["revised"] is None
    assert after["original"]["html"] == PAGE_HTML


def test_confirmed_save_goes_through_existing_sanitized_write(client):
    """确认保存 = 既有 PATCH revision（同一 sanitize_html 净化管线）。"""
    uuid = _seed()
    preview = client.post(
        "/api/v1/library/clips/preview-cleanup",
        json={"html": PAGE_HTML},
    ).json()
    keep_ids = [b["id"] for b in preview["blocks"] if b["keep"]]
    # 注入脏数据块模拟上游内容，确认保存必须把 script 洗掉
    dirty = client.post(
        "/api/v1/library/clips/preview-cleanup",
        json={"html": '<p>正文</p><script>alert("x")</script><p onclick="h()">尾段</p>'},
    )
    assert dirty.status_code == 200

    saved = client.patch(
        f"/api/v1/library/clips/{uuid}/revision",
        json={"blocks": keep_ids, "note": "清理预览确认"},
    )
    assert saved.status_code == 200, saved.text
    detail = client.get(f"/api/v1/library/clips/{uuid}/full").json()
    html = detail["content"]["html"]
    assert "<script" not in html.lower()
    assert "alert" not in html
    assert "onclick" not in html.lower()
    # 保留的块仍然在（标题/导语/图片/结论）
    assert "文章标题" in detail["content"]["text"]
    assert "结论段落" in detail["content"]["text"]
    # 被建议移除的块不再出现
    assert "限时特惠" not in detail["content"]["text"]
    # 原始版本从未被改动
    assert detail["original"]["html"] == PAGE_HTML


def test_preview_rejects_oversize_and_empty(client):
    big = "<p>x</p>" * (60 * 1024)  # > 200KB
    oversize = client.post(
        "/api/v1/library/clips/preview-cleanup", json={"html": big}
    )
    assert oversize.status_code == 422
    empty = client.post("/api/v1/library/clips/preview-cleanup", json={"html": "  "})
    assert empty.status_code == 422
    junk = client.post(
        "/api/v1/library/clips/preview-cleanup", content=b"not json"
    )
    assert junk.status_code == 422
