"""N090 翻译隐私路由 — per-source translation_policy=local_only。

- 来源覆盖：PUT /sources/overrides translationPolicy=local_only（往返 +
  null 清除；非法值 422）；
- 服务端执行点：POST .../translation/segments/generate 对 local_only
  来源 → 403 local_only_policy，且**零 httpx 外呼**（mock spy 断言）；
  lookup（纯缓存读取，从不出网）不受影响；
- fail-open：投影缺失的条目不误伤。
"""

import asyncio

from lumirss.entryref import encode_entry_ref
from lumirss.main import app

FEED_URL = "https://privacy.example/feed.xml"


def _seed_projection(entry_ref: str) -> None:
    async def seed():
        await app.state.db.migrate()
        await app.state.db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, fetched_at)"
            " VALUES (?, ?, ?, ?, ?, '', '', '', '2026-01-01T00:00:00Z', 0)",
            (
                f"urn:test:{entry_ref}",
                entry_ref,
                FEED_URL,
                "隐私来源",
                "标题",
            ),
        )

    asyncio.run(seed())


def test_n090_policy_roundtrip_and_validation(client):
    # 默认：未设置（None = 跟随全局）
    ref = encode_entry_ref("9501")
    _seed_projection(ref)
    result = client.put(
        "/api/v1/sources/overrides",
        json={"feedUrl": FEED_URL, "translationPolicy": "local_only"},
    )
    assert result.status_code == 200, result.text
    assert result.json()["translationPolicy"] == "local_only"

    # 清除（null）
    cleared = client.put(
        "/api/v1/sources/overrides",
        json={"feedUrl": FEED_URL, "translationPolicy": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["translationPolicy"] is None

    # 非法值 → 422 稳定错误
    invalid = client.put(
        "/api/v1/sources/overrides",
        json={"feedUrl": FEED_URL, "translationPolicy": "shout_it_out_loud"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["type"] == "invalid_translation_policy"


def test_n090_generate_rejects_with_zero_httpx_calls(client, monkeypatch):
    """local_only 来源的远程段落生成 → 403 + 无任何 httpx 调用（spy）。"""
    ref = encode_entry_ref("9502")
    _seed_projection(ref)
    assert (
        client.put(
            "/api/v1/sources/overrides",
            json={"feedUrl": FEED_URL, "translationPolicy": "local_only"},
        )
        .status_code
        == 200
    )

    calls: list[tuple[str, str]] = []

    class SpyHttpClient:
        """httpx.AsyncClient 替身：记录一切外呼意图（存在即失败）。"""

        def __init__(self, *args, **kwargs):
            pass

        def build_request(self, method, url, **kwargs):  # noqa: ARG002
            calls.append((method, str(url)))
            raise AssertionError("local_only 来源不得发起任何远程请求")

        def __getattr__(self, name):
            if name in ("aclose", "close"):  # 生命周期方法，不是外呼
                async def _noop():
                    return None

                return _noop

            def _record(*args, **kwargs):
                calls.append((name, str(args[0]) if args else ""))
                raise AssertionError(f"local_only 来源不得外呼（{name}）")

            return _record

    monkeypatch.setattr(app.state, "http_client", SpyHttpClient(), raising=False)

    body = {
        "blocks": [{"index": 0, "text": "需要翻译的段落"}],
    }
    response = client.post(
        f"/api/v1/entries/{ref}/translation/segments/generate", json=body
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["type"] == "local_only_policy"
    assert calls == []  # 零外呼（拒绝发生在任何 provider 调用之前）

    # lookup（纯缓存读取，零 provider 语义）不受策略影响
    lookup = client.post(
        f"/api/v1/entries/{ref}/translation/segments/lookup", json=body
    )
    assert lookup.status_code == 200
    assert calls == []


def test_n090_other_sources_unaffected(client, monkeypatch):
    """未设置策略的来源不误伤：拦截函数放行（此处以策略判定直证 +
    generate 不再返回 403 local_only_policy）。"""
    ref = encode_entry_ref("9503")
    other_feed = "https://normal.example/feed.xml"

    async def seed():
        await app.state.db.migrate()
        await app.state.db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, fetched_at)"
            " VALUES (?, ?, ?, ?, ?, '', '', '', '2026-01-01T00:00:00Z', 0)",
            (f"urn:test:{ref}", ref, other_feed, "正常来源", "标题"),
        )

    asyncio.run(seed())

    # provider 不可用（未配置 AI）→ 报错不是 local_only_policy（策略未拦截）
    response = client.post(
        f"/api/v1/entries/{ref}/translation/segments/generate",
        json={"blocks": [{"index": 0, "text": "hello"}]},
    )
    assert response.status_code != 403 or (
        response.json()["error"]["type"] != "local_only_policy"
    )
