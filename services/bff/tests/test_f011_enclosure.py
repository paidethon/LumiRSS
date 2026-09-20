"""F011 enclosure 透传 —— FreshRSS items 中的 enclosure[] → EntryDetail DTO。

- fixture 带 enclosure 的 FreshRSS 响应 → DTO 原样透传（href/type）；
- 形状异常（非 dict / href 非字符串）保守丢弃；无 enclosure 字段 → []。
"""

import secrets as _secrets

import httpx
import pytest

from lumirss.adapters.freshrss import FreshRSSAdapter
from lumirss.config import FreshRSSSettings

FAKE_SECRET = "fake-test-" + _secrets.token_urlsafe(8)
FAKE_TOKEN = "fake-test-token-f011"
BASE_URL = "http://freshrss-test.local"

ITEM_ID = "tag:google.com,2005:reader/item/000659e07aaee24d"

ENCLOSURE_ITEM = {
    "id": ITEM_ID,
    "title": "播客第 12 期",
    "published": 1787270034,
    "summary": {"content": "<p>本节目音频与文稿</p>"},
    "alternate": [{"href": "http://example.com/ep-12"}],
    "origin": {"streamId": "feed/2", "title": "播客"},
    "categories": ["user/-/state/com.google/reading-list"],
    "enclosure": [
        {"href": "https://audio.example/ep12.mp3", "type": "audio/mpeg", "length": "123"},
        {"href": "https://cdn.example/ep12.txt", "type": "text/plain"},
        {"href": "https://bad.example/broken"},  # 无 type 但 href 合法 → 保留 type=None
        "not-a-dict",
        {"type": "video/mp4"},  # 无 href → 丢弃
        {"href": 42},  # href 非字符串 → 丢弃
    ],
}


def make_settings() -> FreshRSSSettings:
    return FreshRSSSettings(
        _env_file=None,
        FRESHRSS_BASE_URL=BASE_URL,
        FRESHRSS_USERNAME="test-user",
        FRESHRSS_API_PASSWORD=FAKE_SECRET,
    )


def make_adapter(handler) -> FreshRSSAdapter:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    )
    return FreshRSSAdapter(client, make_settings())


@pytest.mark.anyio
async def test_f011_enclosure_passthrough_to_detail_dto():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        return httpx.Response(
            200, json={"id": "x", "items": [ENCLOSURE_ITEM]}
        )

    adapter = make_adapter(handler)
    detail = await adapter.get_entry(ITEM_ID)

    assert len(detail.enclosure) == 3, "形状异常元素丢弃，合法项保留"
    assert detail.enclosure[0].href == "https://audio.example/ep12.mp3"
    assert detail.enclosure[0].type == "audio/mpeg"
    assert detail.enclosure[1].type == "text/plain"
    assert detail.enclosure[2].type is None


@pytest.mark.anyio
async def test_f011_no_enclosure_field_defaults_empty():
    plain = {k: v for k, v in ENCLOSURE_ITEM.items() if k != "enclosure"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        return httpx.Response(200, json={"id": "x", "items": [plain]})

    adapter = make_adapter(handler)
    detail = await adapter.get_entry(ITEM_ID)
    assert detail.enclosure == []
