"""F002 OPML 逐项勾选导入 —— 逐项预览、选中子集导入与边界。

- preview 严格零写入，逐项数组含 status（new/duplicate/invalid/
  category_conflict）与冲突说明；
- import 接受 selected_indexes（仅提交选中项），未选中 → skipped；
- 重复导入幂等（第二次全部 duplicate）；坏 XML / 超限 / 非法参数拒绝。
"""

import secrets as _secrets

from lumirss.adapters.freshrss_control import Category, Subscription
from lumirss.main import app

FAKE_SECRET = "fake-test-" + _secrets.token_urlsafe(8)

F002_OPML = b"""<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <body>
    <outline text="Tech">
      <outline text="Feed A" xmlUrl="https://a.example/rss" />
      <outline text="Feed B" xmlUrl="https://b.example/rss" />
    </outline>
    <outline text="Uncategorized">
      <outline text="Reserved" xmlUrl="https://reserved.example/rss" />
    </outline>
    <outline text="Feed Existing" xmlUrl="https://existing.example/rss" />
    <outline text="Feed Bad" xmlUrl="notaurl" />
  </body>
</opml>
"""


class FakeControlAdapter:
    """与 test_opml.py 同型的最小 control 假件（订阅/分类/移动）。"""

    def __init__(self) -> None:
        self.subscriptions = [
            Subscription(
                stream_id="feed/7",
                title="Feed Existing",
                feed_url="https://existing.example/rss",
            )
        ]
        self.categories = [Category("user/-/label/Uncategorized", "Uncategorized")]
        self.subscribe_calls: list[str] = []
        self.next_id = 100

    async def list_subscriptions(self):
        return list(self.subscriptions)

    async def list_categories(self):
        return list(self.categories)

    async def subscribe(self, feed_url, *, category_id=None, title=None):
        self.subscribe_calls.append(feed_url)
        self.next_id += 1
        subscription = Subscription(
            stream_id=f"feed/{self.next_id}", title=title or feed_url, feed_url=feed_url
        )
        self.subscriptions.append(subscription)
        return subscription

    async def move_category(self, stream_id, category_id):
        pass

    async def move_to_new_category(self, stream_id, label):
        self.categories.append(Category(f"user/-/label/{label}", label))


def _client_with(client, fake):
    app.state.freshrss_control_adapter = fake
    return client


def test_f002_preview_items_and_zero_writes(client):
    fake = FakeControlAdapter()
    _client_with(client, fake)
    body = client.post("/api/v1/opml/import/preview", content=F002_OPML)
    assert body.status_code == 200, body.text
    payload = body.json()
    assert fake.subscribe_calls == [], "preview 严格零写入"
    items = payload["items"]
    by_url = {item["xmlUrl"]: item for item in items}
    assert by_url["https://a.example/rss"]["status"] == "new"
    assert by_url["https://existing.example/rss"]["status"] == "duplicate"
    assert by_url["notaurl"]["status"] == "invalid"
    conflict = by_url["https://reserved.example/rss"]
    assert conflict["status"] == "category_conflict"
    assert conflict["note"] is not None and "保留字" in conflict["note"]
    # 索引稳定且连续
    assert [item["index"] for item in items] == list(range(len(items)))


def test_f002_import_selected_subset_only(client):
    fake = FakeControlAdapter()
    _client_with(client, fake)
    preview = client.post("/api/v1/opml/import/preview", content=F002_OPML).json()
    items = preview["items"]
    # 只选 Feed A（new）、existing（duplicate）与 notaurl（invalid）——
    # 后两者应跳过不写（duplicate 进 duplicates，invalid 进 skipped）
    selected = [
        str(item["index"])
        for item in items
        if item["xmlUrl"]
        in ("https://a.example/rss", "https://existing.example/rss", "notaurl")
    ]
    result = client.post(
        f"/api/v1/opml/import?selected_indexes={','.join(selected)}", content=F002_OPML
    ).json()
    assert [item["feedUrl"] for item in result["added"]] == ["https://a.example/rss"]
    assert fake.subscribe_calls == ["https://a.example/rss"], "未选中的 new 不订阅"
    skipped_urls = {item["feedUrl"]: item["reason"] for item in result["skipped"]}
    assert skipped_urls["https://b.example/rss"] == "not_selected"
    assert skipped_urls["https://reserved.example/rss"] == "not_selected"
    assert skipped_urls["notaurl"] == "invalid", "选中的 invalid 项诚实汇报跳过"
    # 选中的 duplicate 不进 skipped（merge 报告口径：duplicates 已如实列出）
    assert "https://existing.example/rss" not in skipped_urls
    assert any(d["feedUrl"] == "https://existing.example/rss" for d in result["duplicates"])


def test_f002_import_default_all_and_idempotent_reimport(client):
    fake = FakeControlAdapter()
    _client_with(client, fake)
    first = client.post("/api/v1/opml/import", content=F002_OPML).json()
    assert len(first["added"]) == 3  # A / B / reserved（reserved 分类不生效）
    assert first["added"][2]["categoryApplied"] is False
    assert first["added"][2]["categoryLabel"] == "Uncategorized"
    # 不可用项诚实汇报为 skipped（默认全量导入语义下也进入 skipped）
    assert {item["feedUrl"] for item in first["skipped"] if item["reason"] == "invalid"} == {
        "notaurl"
    }
    # 幂等：同一文件再导 → 全部 duplicate，无新增写
    second = client.post("/api/v1/opml/import", content=F002_OPML).json()
    assert second["added"] == []
    assert {d["feedUrl"] for d in second["duplicates"]} >= {
        "https://a.example/rss",
        "https://b.example/rss",
    }


def test_f002_import_invalid_selection_param(client):
    _client_with(client, FakeControlAdapter())
    response = client.post(
        "/api/v1/opml/import?selected_indexes=0,abc", content=F002_OPML
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_selection"


def test_f002_preview_bad_xml_and_oversize(client):
    _client_with(client, FakeControlAdapter())
    # 坏 XML → 稳定 400（既有 OpmlInvalid 映射，见 test_opml.py 546/555）
    bad = client.post("/api/v1/opml/import/preview", content=b"<not-opml/>")
    assert bad.status_code == 400
    oversize = client.post(
        "/api/v1/opml/import/preview", content=b"<opml></opml>" + b"x" * (2 * 1024 * 1024 + 1)
    )
    assert oversize.status_code in (413, 422)
