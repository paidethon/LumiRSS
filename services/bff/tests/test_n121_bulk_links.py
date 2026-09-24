"""N121 粘贴多链接收件箱 — POST /library/bulk-links。

混合批次结果（created/duplicate/failed 逐条上报）、重复检测（库内
幂等 + 批内归一化去重）、单条坏 URL 不影响其余条目；剪藏目标走
服务端管线（测试内替换 fetch），抓取失败按条 failed，绝不回滚整批。
"""

import asyncio

import lumirss.clip_fetch as clip_fetch_module


def run(coro):
    return asyncio.run(coro)


def test_bulk_links_bookmark_mixed_batch(client):
    """混合批次：2 created + 1 duplicate（与库内重复）+ 1 failed（坏 URL）；
    单条失败不影响其余条目。"""
    first = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://a.example/one", "title": "已存在"},
    )
    assert first.status_code == 201
    response = client.post(
        "/api/v1/library/bulk-links",
        json={
            "urls": [
                "https://a.example/one",
                "https://b.example/two?utm_source=x",
                "https://c.example/three",
                "不是 URL",
            ],
            "target": "bookmark",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["target"] == "bookmark"
    assert body["created"] == 2
    assert body["duplicate"] == 1
    assert body["failed"] == 1
    by_status = {}
    for item in body["items"]:
        by_status.setdefault(item["status"], []).append(item)
    assert len(by_status["created"]) == 2
    dup = by_status["duplicate"][0]
    assert dup["url"] == "https://a.example/one"
    assert dup["ref"] == first.json()["ref"]
    failed = by_status["failed"][0]
    assert failed["reason"]


def test_bulk_links_batch_inner_duplicates_detected(client):
    """批内重复（含 utm 追踪参数差异）：第二条 duplicate，不重复创建。"""
    response = client.post(
        "/api/v1/library/bulk-links",
        json={
            "urls": [
                "https://dup.example/page",
                "https://dup.example/page?utm_campaign=bulk",
            ],
            "target": "bookmark",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 1
    assert body["duplicate"] == 1
    listed = client.get("/api/v1/library/bookmarks").json()
    assert len(listed["items"]) == 1


def test_bulk_links_blank_lines_dropped(client):
    response = client.post(
        "/api/v1/library/bulk-links",
        json={"urls": ["  ", "https://ok.example/a", ""], "target": "bookmark"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 1
    assert len(body["items"]) == 1


def test_bulk_links_rejects_over_50(client):
    response = client.post(
        "/api/v1/library/bulk-links",
        json={
            "urls": [f"https://x.example/{i}" for i in range(51)],
            "target": "bookmark",
        },
    )
    assert response.status_code == 422


def test_bulk_links_clip_target_with_one_bad_fetch(client, monkeypatch):
    """剪藏目标：成功的两条入库，抓取失败的那条 failed 且不影响其余。"""

    async def _fake_fetch(url, **kwargs):
        if "bad" in url:
            raise clip_fetch_module.ClipFetchError("页面抓取失败。", "fetch_failed")
        return clip_fetch_module.ExtractedPage(
            url=url,
            final_url=url,
            title=f"标题 {url}",
            byline=None,
            content_html=f"<p>{url} 的正文</p>",
            content_text=f"{url} 的正文",
        )

    monkeypatch.setattr(clip_fetch_module, "fetch_extract_sanitize", _fake_fetch)
    response = client.post(
        "/api/v1/library/bulk-links",
        json={
            "urls": [
                "https://good.example/1",
                "https://bad.example/2",
                "https://good.example/3",
            ],
            "target": "clip",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] == 2
    assert body["failed"] == 1
    failed_item = next(i for i in body["items"] if i["status"] == "failed")
    assert "bad.example" in failed_item["url"]
    assert failed_item["reason"]
    listed = client.get("/api/v1/library/clips").json()
    assert {item["title"] for item in listed["items"]} == {
        "标题 https://good.example/1",
        "标题 https://good.example/3",
    }


def test_bulk_links_clip_duplicate_within_library(client, monkeypatch):
    """剪藏幂等：同一 URL 二次批量 → duplicate（与单个创建同语义）。"""

    async def _fake_fetch(url, **kwargs):
        return clip_fetch_module.ExtractedPage(
            url=url,
            final_url=url,
            title="同一篇",
            byline=None,
            content_html="<p>正文</p>",
            content_text="正文",
        )

    monkeypatch.setattr(clip_fetch_module, "fetch_extract_sanitize", _fake_fetch)
    first = client.post(
        "/api/v1/library/bulk-links",
        json={"urls": ["https://same.example/a"], "target": "clip"},
    )
    assert first.status_code == 200
    assert first.json()["created"] == 1
    second = client.post(
        "/api/v1/library/bulk-links",
        json={"urls": ["https://same.example/a"], "target": "clip"},
    )
    assert second.status_code == 200
    assert second.json()["created"] == 0
    assert second.json()["duplicate"] == 1
