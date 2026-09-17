"""§12.5 邮件桥取消订阅匹配修复的回归测试。

历史缺陷：generated URL 是 ``{base}/feeds/mail/{uuid}.{secret}.atom``，
旧逻辑 ``feed_url.endswith(f"/feeds/mail/{uuid}.")`` 永不匹配 → 删除
列表时取消订阅静默假成功（死订阅残留）。本文件用真实形状的 URL 夹具
验证：正确匹配本 connector 身份；相近 uuid、不同 host、不同 secret 的
其它订阅不被误删；重复调用幂等。"""

import asyncio
from types import SimpleNamespace

from lumirss.main import app
from lumirss.routers.mail import _unsubscribe_required


def run(coroutine):
    return asyncio.run(coroutine)


class FakeControlAdapter:
    def __init__(self, subscriptions):
        self._subscriptions = subscriptions
        self.unsubscribed: list[str] = []
        self.subscribed: list[str] = []

    async def list_subscriptions(self):
        return list(self._subscriptions)

    async def unsubscribe(self, stream_id):
        self.unsubscribed.append(stream_id)
        self._subscriptions = [
            s for s in self._subscriptions if s.stream_id != stream_id
        ]

    async def subscribe(self, url, title=""):
        self.subscribed.append(url)
        return SimpleNamespace(stream_id=f"new-{len(self.subscribed)}")


def _sub(stream_id: str, feed_url: str):
    return SimpleNamespace(stream_id=stream_id, feed_url=feed_url)


UUID = "5f0a9c1e-1234-4abc-9def-001122334455"
SECRET = "s3cretv4l"


def _install(subscriptions):
    adapter = FakeControlAdapter(subscriptions)
    app.state.freshrss_control_adapter = adapter
    return adapter


def test_real_shaped_subscription_is_matched_and_unsubscribed(client):
    adapter = _install(
        [
            _sub("sid-1", f"https://rss.example.com/feeds/mail/{UUID}.{SECRET}.atom"),
        ]
    )
    request = SimpleNamespace(app=app)
    error = run(_unsubscribe_required(request, UUID))
    assert error is None
    assert adapter.unsubscribed == ["sid-1"]


def test_similar_uuid_and_other_feeds_are_not_touched(client):
    adapter = _install(
        [
            # 相近 uuid 的另一列表（本 uuid 是它的前缀）
            _sub("sid-2", f"https://rss.example.com/feeds/mail/{UUID}extra.{SECRET}.atom"),
            # 同一 uuid 但非本 connector 路径形状（无 .atom）
            _sub("sid-3", f"https://rss.example.com/feeds/mail/{UUID}.{SECRET}"),
            # 普通 RSS 订阅
            _sub("sid-4", "https://blog.example.com/feed.xml"),
        ]
    )
    request = SimpleNamespace(app=app)
    error = run(_unsubscribe_required(request, UUID))
    assert error is None, "没有可取消的订阅时是幂等成功"
    assert adapter.unsubscribed == []


def test_delete_bridge_list_endpoint_unsubscribes_first(client):
    """端到端：创建列表（自动订阅进 fake FreshRSS）→ 删除 → fake 中
    对应订阅被移除（旧逻辑在这里会静默残留）。"""
    adapter = _install([])
    created = client.post(
        "/api/v1/mail/bridge-lists", json={"name": "回归测试列表"}
    ).json()
    assert created["atomPath"].endswith(".atom")
    # 自动订阅 best-effort：fake adapter 已记录
    assert any(created["atomPath"] in url for url in adapter.subscribed)
    # 手工构造与生产一致的订阅行（含完整 secret+atom 后缀）
    adapter._subscriptions = [
        _sub(
            "sid-live",
            f"https://rss.example.com{created['atomPath']}",
        )
    ]
    response = client.delete(f"/api/v1/mail/bridge-lists/{created['uuid']}")
    assert response.status_code == 204, response.text
    assert adapter.unsubscribed == ["sid-live"]
