"""F003 按所选导出 OPML —— 选择过滤、分类结构保留与转义。

- 未选不泄露：selected 导出不含未选中的订阅；
- 中文/特殊字符经 XML 转义；导出文件可被 parse_opml 再导入（roundtrip）；
- 跨分类选择；缺省参数 = 全库透传（向后兼容）；非法 ref → 400。
"""

import secrets as _secrets

from lumirss.adapters.freshrss_control import Category, Subscription
from lumirss.main import app
from lumirss.opml import parse_opml


class FakeControlAdapter:
    def __init__(self) -> None:
        # refs 对应 s1.<base64url(feed/N)> —— 由 encode 现算，不手拼
        from lumirss.subscriptionref import encode_subscription_ref

        self.subscriptions = [
            Subscription(
                stream_id="feed/1",
                title="科技日报 <A&B>",
                feed_url="https://tech.example/rss?a=1&b=2",
                category_id="user/-/label/科技",
                category_label="科技",
            ),
            Subscription(
                stream_id="feed/2",
                title="新闻晚报",
                feed_url="https://news.example/rss",
                category_id="user/-/label/新闻",
                category_label="新闻",
            ),
            Subscription(
                stream_id="feed/3",
                title="独立博客",
                feed_url="https://blog.example/rss",
            ),
        ]
        self.ref_of = {
            s.feed_url: encode_subscription_ref(s.stream_id) for s in self.subscriptions
        }
        self.categories = [
            Category("user/-/label/科技", "科技"),
            Category("user/-/label/新闻", "新闻"),
        ]
        self.export_called = False

    async def list_subscriptions(self):
        return list(self.subscriptions)

    async def list_categories(self):
        return list(self.categories)

    async def export_opml(self) -> bytes:
        self.export_called = True
        return b"<opml><body /></opml>"


def _client_with(client, fake):
    app.state.freshrss_control_adapter = fake
    return client


def test_f003_selected_export_roundtrip_and_no_leak(client):
    fake = FakeControlAdapter()
    _client_with(client, fake)
    # 只选「科技日报」与「独立博客」（跨分类 + 未分组）
    response = client.get(
        "/api/v1/opml/export?subscription_refs="
        + fake.ref_of["https://tech.example/rss?a=1&b=2"]
        + "&subscription_refs="
        + fake.ref_of["https://blog.example/rss"]
    )
    assert response.status_code == 200
    body = response.content
    parsed = parse_opml(body)  # 导出再导入可用
    urls = {e.feed_url for e in parsed.entries}
    assert urls == {"https://tech.example/rss?a=1&b=2", "https://blog.example/rss"}
    assert "https://news.example/rss" not in urls, "未选中项不泄露"
    # 分类结构保留：科技有容器，独立博客未分组
    assert parsed.entries[0].category_label == "科技"
    assert parsed.entries[1].category_label is None
    # 特殊字符转义（title 含 <A&B>，URL 含 &）
    text = body.decode("utf-8")
    assert "<A&B>" not in text, "原始 < & 不得未转义出现"
    assert "&amp;" in text and "&lt;" in text
    # 中文分类名原样保留（UTF-8 合法）
    assert "科技" in text


def test_f003_category_selection_and_default_passthrough(client):
    fake = FakeControlAdapter()
    _client_with(client, fake)
    response = client.get(
        "/api/v1/opml/export?category_ids=user/-/label/新闻"
    )
    assert response.status_code == 200
    parsed = parse_opml(response.content)
    assert [e.feed_url for e in parsed.entries] == ["https://news.example/rss"]

    # 缺省 = 全库，走上游透传（不重建文档）
    fake2 = FakeControlAdapter()
    _client_with(client, fake2)
    plain = client.get("/api/v1/opml/export")
    assert plain.status_code == 200
    assert fake2.export_called is True
    assert plain.content == b"<opml><body /></opml>"


def test_f003_invalid_or_unknown_ref_rejected(client):
    fake = FakeControlAdapter()
    _client_with(client, fake)
    bad = client.get("/api/v1/opml/export?subscription_refs=garbage!!!")
    assert bad.status_code == 400
    unknown = client.get(
        "/api/v1/opml/export?subscription_refs=s1." + _secrets.token_urlsafe(6)
    )
    assert unknown.status_code == 400
