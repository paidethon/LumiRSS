"""FIX-232 — Google Reader 长 ID 全链路无损字符串。

缺陷：长条目 ID（16-hex 长形 / 超过 2^53 的十进制短形）在任何环节被
转成 JavaScript number 语义（float/不安全整数）后会丢失精度，导致
状态读写打到错误条目。承诺：ID 从上游 JSON 到 entryRef 再到 edit-tag
请求体始终是精确字符串。

覆盖：
- 16-hex 长形 ID（> 2^53）：list → entryRef → decode 精确往返；
  set_entry_state 的 edit-tag 表单字段 ``i`` 携带精确原串。
- 十进制短形字符串 ID > 2^53：同上精确往返。
- 上游把短形 ID 发成 JSON number（int）时：Python 整数解析天然无损，
  适配层应转成精确十进制字符串（绝不经过 float）。
- 上游发成 JSON float（JS double 语义，精度已损）时：绝不臆造数字，
  条目跳过（形状异常降级），不产生假 ID。
"""

import secrets as _secrets
import urllib.parse

import httpx
import pytest

from lumirss.adapters.freshrss import FreshRSSAdapter
from lumirss.config import FreshRSSSettings
from lumirss.entryref import decode_entry_ref

FAKE_SECRET = "fake-test-" + _secrets.token_urlsafe(8)
FAKE_TOKEN = "fake-test-token-fix232"
BASE_URL = "http://freshrss-test.local"

# > 2^53 (9007199254740992) 的 16-hex 长形 ID 与十进制短形 ID。
LONG_HEX_ID = "tag:google.com,2005:reader/item/0020000000000001"
LONG_DECIMAL_ID = "9007199254740993"


def make_adapter(handler) -> tuple[FreshRSSAdapter, list[httpx.Request]]:
    requested: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(recording), trust_env=False)
    settings = FreshRSSSettings(
        _env_file=None,
        FRESHRSS_BASE_URL=BASE_URL,
        FRESHRSS_USERNAME="test-user",
        FRESHRSS_API_PASSWORD=FAKE_SECRET,
    )
    return FreshRSSAdapter(client, settings), requested


def login_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")


def stream_fixture(item_ids: list) -> dict:
    return {
        "id": "user/-/state/com.google/reading-list",
        "updated": 1787270034,
        "items": [
            {
                "id": item_id,
                "title": f"entry-{index}",
                "published": 1787270034,
                "origin": {"streamId": "feed/1", "title": "Feed"},
                "alternate": [{"href": f"http://example.com/{index}"}],
                "categories": [],
            }
            for index, item_id in enumerate(item_ids)
        ],
    }


def routed(handler):
    def full(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return login_ok(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(200, text=FAKE_TOKEN)
        if request.url.path.endswith("/subscription/list"):
            return httpx.Response(200, json={"subscriptions": []})
        return handler(request)

    return full


@pytest.mark.anyio
async def test_fix232_long_hex_id_roundtrips_exactly_through_list_and_state_write():
    """16-hex 长形 ID：列表 entryRef 解码 == 精确原串；edit-tag i == 精确原串。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/stream/contents/reading-list"):
            return httpx.Response(200, json=stream_fixture([LONG_HEX_ID]))
        if request.url.path.endswith("/edit-tag"):
            return httpx.Response(200, text="OK")
        raise AssertionError(f"unexpected path {request.url.path}")

    adapter, requested = make_adapter(routed(handler))

    page = await adapter.list_entries()
    assert len(page.items) == 1
    assert decode_entry_ref(page.items[0].entryRef) == LONG_HEX_ID

    await adapter.set_entry_state(LONG_HEX_ID, read=True)
    edit = next(r for r in requested if r.url.path.endswith("/edit-tag"))
    body = urllib.parse.unquote(edit.content.decode())
    assert f"i={LONG_HEX_ID}" in body


@pytest.mark.anyio
async def test_fix232_decimal_string_id_beyond_2_power_53_roundtrips_exactly():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/stream/contents/reading-list"):
            return httpx.Response(200, json=stream_fixture([LONG_DECIMAL_ID]))
        if request.url.path.endswith("/edit-tag"):
            return httpx.Response(200, text="OK")
        raise AssertionError(f"unexpected path {request.url.path}")

    adapter, requested = make_adapter(routed(handler))

    page = await adapter.list_entries()
    assert len(page.items) == 1
    decoded = decode_entry_ref(page.items[0].entryRef)
    assert decoded == LONG_DECIMAL_ID
    # 全链路无 float 语义：解码结果仍是字符串且逐字符等于原串。
    assert isinstance(decoded, str)
    assert decoded.isascii() and decoded.isdigit()

    await adapter.set_entry_state(LONG_DECIMAL_ID, starred=True)
    edit = next(r for r in requested if r.url.path.endswith("/edit-tag"))
    body = urllib.parse.unquote(edit.content.decode())
    assert f"i={LONG_DECIMAL_ID}" in body


@pytest.mark.anyio
async def test_fix232_json_number_id_stays_exact_string_never_float():
    """上游发 JSON number（int）：Python 整数解析无损，适配层必须产出
    精确十进制字符串 ID（绝不经过 float/JS number 语义）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/stream/contents/reading-list"):
            # 原始 JSON 里 ID 就是不带引号的数字（超过 2^53）。
            raw = (
                '{"id": "user/-/state/com.google/reading-list", "items": ['
                '{"id": 9007199254740993, "title": "numeric-id-entry", '
                '"published": 1787270034, "categories": [], '
                '"origin": {"streamId": "feed/1", "title": "Feed"}, '
                '"alternate": [{"href": "http://example.com/n"}]}]}'
            )
            return httpx.Response(
                200, content=raw.encode(), headers={"content-type": "application/json"}
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    adapter, _ = make_adapter(routed(handler))

    page = await adapter.list_entries()
    assert len(page.items) == 1, "JSON number ID 的条目不得丢失"
    decoded = decode_entry_ref(page.items[0].entryRef)
    assert decoded == "9007199254740993"
    assert decoded.isdigit() and isinstance(decoded, str)


@pytest.mark.anyio
async def test_fix232_float_id_is_never_reinterpreted_as_digits():
    """上游发 JSON float（精度已损的 JS double 形状）：绝不臆造十进制
    数字串（那会写到错误条目），条目按形状异常诚实跳过。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/stream/contents/reading-list"):
            raw = (
                '{"id": "user/-/state/com.google/reading-list", "items": ['
                '{"id": 9.007199254740993e15, "title": "float-id-entry", '
                '"published": 1787270034, "categories": []}]}'
            )
            return httpx.Response(
                200, content=raw.encode(), headers={"content-type": "application/json"}
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    adapter, _ = make_adapter(routed(handler))

    page = await adapter.list_entries()
    assert page.items == [], "float ID 不得被转换成（可能错误的）数字串"
