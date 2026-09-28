"""FIX-234 — 缺省分类映射：空/缺分类绝不生成「undefined」分类。

缺陷：FreshRSS 订阅项的 categories[0] 缺 label、缺 id 或 label 段为空
（``user/-/label/``）时，映射结果要么丢失订阅关系（round-trip 后归入
无分类），要么把空串/缺失值透传给客户端渲染成字面「undefined」分类。

承诺（greader 单分类模型，id = 稳定 key = ``user/-/label/<名>``）：

- id 在、label 缺 → label 回退为 id 的 label 段（与 /api/v1/categories
  的构造规则一致）——订阅关系往返保留；
- label 在、id 缺 → id 按 label 段规则合成——同一条稳定 key；
- label 段为空（``user/-/label/``）或全部缺失 → 无分类（None, None），
  绝不产生空名/undefined 名分类。
"""

import secrets as _secrets

import httpx
import pytest

from lumirss.adapters.freshrss import (
    FreshRSSAdapter,
    category_of_first,
)
from lumirss.adapters.freshrss_control import FreshRSSControlAdapter, FreshRSSSession
from lumirss.config import FreshRSSSettings

FAKE_SECRET = "fake-test-" + _secrets.token_urlsafe(8)
FAKE_TOKEN = "fake-test-token-fix234"
BASE_URL = "http://freshrss-test.local"


def make_settings() -> FreshRSSSettings:
    return FreshRSSSettings(
        _env_file=None,
        FRESHRSS_BASE_URL=BASE_URL,
        FRESHRSS_USERNAME="test-user",
        FRESHRSS_API_PASSWORD=FAKE_SECRET,
    )


def make_read_adapter(handler) -> FreshRSSAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    return FreshRSSAdapter(client, make_settings())


def make_control(handler) -> FreshRSSControlAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    session = FreshRSSSession(client, make_settings())
    return FreshRSSControlAdapter(session)


def greader_handler(*, subscriptions: dict | None = None, tags: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accounts/ClientLogin"):
            return httpx.Response(200, text=f"Auth={FAKE_TOKEN}\n")
        if request.url.path.endswith("/subscription/list"):
            return httpx.Response(200, json=subscriptions or {"subscriptions": []})
        if request.url.path.endswith("/tag/list"):
            return httpx.Response(200, json=tags or {"tags": []})
        raise AssertionError(f"unexpected path {request.url.path}")

    return handler


# --- category_of_first 单元映射 ---------------------------------------------


def test_fix234_id_present_label_missing_derives_label_from_id():
    category_id, category_label = category_of_first(
        {"categories": [{"id": "user/-/label/Tech"}]}
    )
    assert (category_id, category_label) == ("user/-/label/Tech", "Tech")


def test_fix234_label_present_id_missing_synthesizes_id():
    category_id, category_label = category_of_first(
        {"categories": [{"label": "Tech"}]}
    )
    assert (category_id, category_label) == ("user/-/label/Tech", "Tech")


def test_fix234_empty_label_segment_maps_to_no_category():
    """``user/-/label/``（label 段为空）不是可用分类：无分类，绝不产出
    空名/undefined 名分类。"""
    assert category_of_first(
        {"categories": [{"id": "user/-/label/", "label": ""}]}
    ) == (None, None)


def test_fix234_whitespace_label_falls_back_to_id_segment():
    category_id, category_label = category_of_first(
        {"categories": [{"id": "user/-/label/Tech", "label": "   "}]}
    )
    assert (category_id, category_label) == ("user/-/label/Tech", "Tech")


def test_fix234_shape_anomalies_still_degrade_to_no_category():
    assert category_of_first({}) == (None, None)
    assert category_of_first({"categories": []}) == (None, None)
    assert category_of_first({"categories": ["not-a-dict"]}) == (None, None)
    # id 形状异常但 label 可用：与「label 在、id 缺」同一规则——按 label
    # 合成稳定 key，订阅关系不丢。
    assert category_of_first({"categories": [{"id": 42, "label": "x"}]}) == (
        "user/-/label/x",
        "x",
    )
    # id、label 都不可用：无分类。
    assert category_of_first({"categories": [{"id": 42}]}) == (None, None)


# --- 读路径 round-trip：订阅关系保留 ----------------------------------------


@pytest.mark.anyio
async def test_fix234_list_feeds_preserves_subscription_relation_without_label():
    payload = {
        "subscriptions": [
            {
                "id": "feed/7",
                "title": "只有 id 的分类",
                "url": "https://example.com/feed.xml",
                "categories": [{"id": "user/-/label/Tech"}],
            },
            {
                "id": "feed/8",
                "title": "空 label 段",
                "url": "https://example.org/rss.xml",
                "categories": [{"id": "user/-/label/", "label": ""}],
            },
        ]
    }
    adapter = make_read_adapter(greader_handler(subscriptions=payload))
    feeds = await adapter.list_feeds()
    assert feeds[0].category_id == "user/-/label/Tech"
    assert feeds[0].category_label == "Tech", "缺 label 不得让订阅关系丢失"
    assert feeds[1].category_id is None
    assert feeds[1].category_label is None


@pytest.mark.anyio
async def test_fix234_control_list_categories_skips_empty_label_folder():
    tags = {
        "tags": [
            {"id": "user/-/label/新闻", "type": "folder", "sortid": "A1"},
            {"id": "user/-/label/", "type": "folder", "sortid": "A2"},
            {"id": "user/-/state/com.google/starred", "type": "starred"},
        ]
    }
    control = make_control(greader_handler(tags=tags))
    categories = await control.list_categories()
    assert [category.label for category in categories] == ["新闻"], (
        "空 label 段的 folder 不是分类，绝不出现在分类列表里"
    )
