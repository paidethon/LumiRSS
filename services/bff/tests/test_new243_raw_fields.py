"""NEW-243 原始 feed 字段查看器 — 脱敏字段 + 应用映射 + 错误映射报告 + 隔离。

- 脱敏：url 只显示 scheme+host+path（query 里的令牌不出现）；正文
  只显示长度 + sha256 指纹（正文本身不进查看器）；title/author 原样；
- 每个字段带 appMapping（应用把它映射成了什么）；
- 报告：POST 追加台账 → GET 可见；空 problem 422；未知条目 404；
- 隔离：A 的映射报告对 B 不可见（真实 RoutingDatabase）。
"""

import asyncio

from lumirss.entryref import encode_entry_ref
from new231_helpers import ab_session


def _seed_entry(client, item_id: str, *, url: str, content: str) -> str:
    entry_ref = encode_entry_ref(item_id)
    app = client.app

    async def _seed():
        await app.state.db.migrate()
        await app.state.db.execute(
            "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) "
            "VALUES (?, ?, 'https://f.example/rss', '源', '字段查看文章', '作者甲', ?, ?, '2026-09-01T00:00:00+00:00', 0, 0, 0)",
            (item_id, entry_ref, url, content),
        )

    asyncio.run(_seed())
    return entry_ref


def test_new243_raw_fields_sanitized_with_mapping(client):
    """url 的 query 不出现；正文以指纹呈现；每个字段带映射说明。"""
    entry_ref = _seed_entry(
        client,
        "rf-1",
        url="https://u.example/article?session_token=abc123&utm_source=x",
        content="正文第一段。\n\n正文第二段。",
    )
    view = client.get(f"/api/v1/entries/{entry_ref}/raw-fields")
    assert view.status_code == 200, view.text
    body = view.json()
    fields = {f["key"]: f for f in body["fields"]}
    assert set(fields) == {"title", "author", "url", "published_at", "feed_title", "content_text"}

    url_field = fields["url"]
    assert url_field["value"] == "https://u.example/article"
    assert "session_token" not in str(url_field["value"]) and "utm_source" not in str(url_field["value"])
    assert url_field["appMapping"]

    content_field = fields["content_text"]
    assert content_field["value"]["present"] is True
    assert content_field["value"]["chars"] == len("正文第一段。\n\n正文第二段。")
    assert len(content_field["value"]["sha256Prefix"]) == 16
    assert "正文第一段" not in str(content_field["value"])  # 正文不进查看器

    assert fields["title"]["value"] == "字段查看文章"
    assert fields["author"]["value"] == "作者甲"

    # 投影未命中 → 404（诚实：没有数据可看）
    missing = client.get("/api/v1/entries/e1.nope/raw-fields")
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "raw_fields_not_found"


def test_new243_report_wrong_mapping_and_validation(client):
    """报告错误映射 → 台账可见；空 problem 422。"""
    entry_ref = _seed_entry(client, "rf-2", url="https://u.example/b", content="正文")
    report = client.post(
        f"/api/v1/entries/{entry_ref}/raw-fields/reports",
        json={"fieldKey": "author", "problem": "作者列显示的是 feed 名，不是文章作者", "expected": "应为署名作者"},
    )
    assert report.status_code == 201, report.text
    body = report.json()
    assert body["fieldKey"] == "author"
    assert body["problem"].startswith("作者列")

    listed = client.get(f"/api/v1/entries/{entry_ref}/raw-fields/reports")
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["expected"] == "应为署名作者"

    bad = client.post(
        f"/api/v1/entries/{entry_ref}/raw-fields/reports",
        json={"fieldKey": "author", "problem": "   "},
    )
    assert bad.status_code == 422


def test_new243_isolation_between_users(monkeypatch, tmp_path):
    """A 的映射报告对 B 不可见（真实 RoutingDatabase per-user 库）。"""
    with ab_session(monkeypatch, tmp_path) as session:
        member = session.activate_member("n24x-b")
        entry_ref = encode_entry_ref("rf-iso")
        created = session.client.post(
            f"/api/v1/entries/{entry_ref}/raw-fields/reports",
            json={"fieldKey": "title", "problem": "A 看到的映射问题"},
            headers=session.owner,
        )
        assert created.status_code == 201, created.text

        b_list = session.client.get(
            f"/api/v1/entries/{entry_ref}/raw-fields/reports", headers=member
        )
        assert b_list.status_code == 200
        assert b_list.json()["items"] == []

        a_list = session.client.get(
            f"/api/v1/entries/{entry_ref}/raw-fields/reports", headers=session.owner
        )
        assert len(a_list.json()["items"]) == 1
