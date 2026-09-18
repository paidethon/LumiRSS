"""F14 失效来源替换预览 — 只读发现候选（错误为 200 空候选降级）。"""

from types import SimpleNamespace

from lumirss.main import app


def test_replacement_preview_lists_candidates_excluding_current(client):
    async def _discover(url: str):
        if "dead.example.com" not in url:
            return []
        return [
            SimpleNamespace(
                feed_url="https://dead.example.com/feed.xml", title="失效源", source="probed", format="rss"
            ),
            SimpleNamespace(
                feed_url="https://dead.example.com/feed.xml", title="失效源", source="probed", format="rss"
            ),
        ]

    app.state.source_discovery_service = SimpleNamespace(discover=_discover)
    response = client.get(
        "/api/v1/sources/replacement-preview?feedUrl=https%3A%2F%2Fdead.example.com%2Ffeed.xml"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["candidates"] == []  # 全部候选等于当前 feed → 排除后为空
    assert body["note"]


def test_replacement_preview_discovery_failure_degrades(client):
    async def _fail(url: str):
        raise RuntimeError("site down")

    app.state.source_discovery_service = SimpleNamespace(discover=_fail)
    response = client.get(
        "/api/v1/sources/replacement-preview?feedUrl=https%3A%2F%2Fdead.example.com%2Ffeed.xml"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["candidates"] == []
    assert "发现失败" in body["note"]
