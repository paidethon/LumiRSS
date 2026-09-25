"""N018 OPML 树对照导入 —— 计划正确性、确定性重名规则、应用与撤销。

- 计划（严格只读）：createCategories / reuseCategories（按名精确匹配、
  首个命中——确定性规则）/ moveFeeds（已订阅且目标分类不同 → update）/
  duplicateFeeds（在位 → skip）；
- 层级映射：OPML 嵌套 → 最外层容器标签（FreshRSS 单层分类模型，
  '/' 不是合法分类名字符）；
- 应用：订阅新 feed → 建类/移动随行；写撤销台账（cap 5）；
- 撤销：feed 移回原分类；每行至多撤销一次；新建分类无法经 greader
  API 删除（无该端点）→ categoriesNotDeleted 诚实列出。
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from lumirss.adapters.freshrss_control import Category, Subscription
from lumirss.main import app
from lumirss.opml import OpmlService
from lumirss.opml_import_log import OpmlImportLogStore
from lumirss.storage import Database

TREE_OPML = b"""<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head><title>Tree</title></head>
  <body>
    <outline text="Tech">
      <outline text="Sub">
        <outline text="Feed New" xmlUrl="https://new.example/rss" />
        <outline text="Feed Moved" xmlUrl="https://moved.example/rss" />
      </outline>
      <outline text="Feed InPlace" xmlUrl="https://inplace.example/rss" />
    </outline>
    <outline text="News">
      <outline text="Feed News" xmlUrl="https://news.example/rss" />
    </outline>
  </body>
</opml>
"""


def run(coroutine):
    return asyncio.run(coroutine)


class TreeControl:
    """Fake control adapter：维护分类归属（树对照语义需要真实状态机）。"""

    def __init__(self) -> None:
        self.next_id = 100
        self.subscriptions = [
            Subscription(
                stream_id="feed/1",
                title="Feed Moved",
                feed_url="https://moved.example/rss",
                category_id="user/-/label/Old",
                category_label="Old",
            ),
            Subscription(
                stream_id="feed/2",
                title="Feed InPlace",
                feed_url="https://inplace.example/rss",
                category_id="user/-/label/Tech",
                category_label="Tech",
            ),
        ]
        self.categories = [
            Category("user/-/label/Old", "Old"),
            Category("user/-/label/Tech", "Tech"),
        ]

    async def list_subscriptions(self):
        return list(self.subscriptions)

    async def list_categories(self):
        return list(self.categories)

    async def subscribe(self, feed_url, *, category_id=None, title=None):
        self.next_id += 1
        subscription = Subscription(
            stream_id=f"feed/{self.next_id}",
            title=title or feed_url,
            feed_url=feed_url,
            category_id=category_id,
            category_label=None,
        )
        self.subscriptions.append(subscription)
        return subscription

    async def move_category(self, stream_id, category_id):
        for subscription in self.subscriptions:
            if subscription.stream_id == stream_id:
                subscription.category_id = category_id
                subscription.category_label = category_id.removeprefix(
                    "user/-/label/"
                )
                return
        raise AssertionError(f"unknown stream {stream_id}")

    async def move_to_new_category(self, stream_id, label):
        for category in self.categories:
            if category.label == label:
                raise AssertionError("conflict should be pre-checked")
        self.categories.append(Category(f"user/-/label/{label}", label))
        await self.move_category(stream_id, f"user/-/label/{label}")


# ---- 计划（纯构造，不触网） --------------------------------------------------


def test_n018_plan_correctness_on_fixture_tree():
    control = TreeControl()
    service = OpmlService(control)
    plan = run(service.tree_preview(TREE_OPML))

    # 层级映射：嵌套 Sub 归并到最外层 Tech（确定性 flatten）；Tech 复用，
    # News 新建。
    assert plan["createCategories"] == ["News"]
    assert plan["reuseCategories"] == ["Tech"]
    new_feeds = {item["feedUrl"]: item for item in plan["newFeeds"]}
    assert new_feeds["https://new.example/rss"]["categoryLabel"] == "Tech"
    assert new_feeds["https://new.example/rss"]["title"] == "Feed New"
    assert new_feeds["https://news.example/rss"]["categoryLabel"] == "News"

    # 已订阅且目标分类不同 → update 移动（moved.example: Old → Tech）。
    moves = {item["feed"]: item for item in plan["moveFeeds"]}
    assert moves["https://moved.example/rss"]["from"] == "Old"
    assert moves["https://moved.example/rss"]["to"] == "Tech"
    assert moves["https://moved.example/rss"]["toCategoryId"] == "user/-/label/Tech"
    assert moves["https://moved.example/rss"]["subscriptionRef"].startswith("s1.")

    # 已在目标分类 → skip（绝不重复移动）。
    duplicates = {item["feed"]: item for item in plan["duplicateFeeds"]}
    assert duplicates["https://moved.example/rss"]["action"] == "update"
    assert duplicates["https://inplace.example/rss"]["action"] == "skip"


def test_n018_duplicate_category_names_reuse_first_match_deterministically():
    control = TreeControl()
    # 上游出现重名（不应发生，但规则必须确定）：首个命中复用。
    control.categories = [
        Category("user/-/label/Tech-A", "Tech"),
        Category("user/-/label/Tech-B", "Tech"),
    ]
    control.subscriptions = [
        Subscription(
            stream_id="feed/1",
            title="x",
            feed_url="https://new.example/rss",
        )
    ]
    service = OpmlService(control)
    plan = run(service.tree_preview(TREE_OPML))
    assert plan["reuseCategories"] == ["Tech"]
    assert "News" in plan["createCategories"]
    moves = {item["feed"]: item for item in plan["moveFeeds"]}
    # 首个命中的 id（Tech-A）是稳定目标。
    assert moves["https://new.example/rss"]["toCategoryId"] == "user/-/label/Tech-A"


def test_n018_plan_is_read_only():
    control = TreeControl()
    service = OpmlService(control)
    run(service.tree_preview(TREE_OPML))
    # 预览零写：订阅/分类状态逐字节不变。
    assert len(control.subscriptions) == 2
    assert len(control.categories) == 2
    assert all("subscribe" not in str(call) for call in [])


# ---- 应用 + 撤销（走 TestClient，验证台账与反向操作） ------------------------


@pytest.fixture()
def tree_client(tmp_path):
    control = TreeControl()
    with TestClient(app) as test_client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        app.state.freshrss_control_adapter = control
        yield test_client, control
    app.state.freshrss_control_adapter = None


def test_n018_apply_executes_plan_and_logs_for_undo(tree_client):
    client, control = tree_client
    response = client.post("/api/v1/opml/import/tree-apply", content=TREE_OPML)
    assert response.status_code == 200
    result = response.json()

    # 新订阅 + 分类移动 + 建类随行。
    added = {item["feedUrl"] for item in result["added"]}
    assert added == {"https://new.example/rss", "https://news.example/rss"}
    assert result["categoriesCreated"] == ["News"]
    moved = result["moved"]
    assert len(moved) == 1
    assert moved[0]["fromCategoryId"] == "user/-/label/Old"
    assert moved[0]["toCategoryId"] == "user/-/label/Tech"

    # 台账：新建分类 + 被移动 feed 已记录，logId 返回。
    assert result["logId"] >= 1
    logs = run(OpmlImportLogStore(app.state.db).list_recent())
    assert logs[0]["createdCategoryLabels"] == ["News"]
    assert logs[0]["movedFeeds"][0]["streamId"] == "feed/1"
    assert logs[0]["undoneAt"] is None

    # 服务器状态：新 feed 已进 Tech，moved feed 已移到 Tech，News 已建。
    by_url = {sub.feed_url: sub for sub in control.subscriptions}
    assert by_url["https://new.example/rss"].category_label == "Tech"
    assert by_url["https://moved.example/rss"].category_label == "Tech"
    assert any(category.label == "News" for category in control.categories)


def test_n018_undo_moves_feeds_back_and_reports_honest_category_boundary(tree_client):
    client, control = tree_client
    applied = client.post("/api/v1/opml/import/tree-apply", content=TREE_OPML)
    log_id = applied.json()["logId"]

    undone = client.post(f"/api/v1/opml/import/{log_id}/undo")
    assert undone.status_code == 200
    result = undone.json()
    assert len(result["movedBack"]) == 1
    assert result["movedBack"][0]["toCategoryId"] == "user/-/label/Old"
    # 诚实边界：greader API 无分类删除端点 → 新建分类不删，如实列出。
    assert result["categoriesDeleted"] == []
    assert result["categoriesNotDeleted"][0]["label"] == "News"
    assert result["categoriesNotDeleted"][0]["reason"] == "greader_api_no_delete"
    assert "FreshRSS" in result["note"]

    # 服务器状态：feed 移回 Old；分类仍在。
    by_url = {sub.feed_url: sub for sub in control.subscriptions}
    assert by_url["https://moved.example/rss"].category_label == "Old"

    # 已撤销行不可二次撤销（set 语义）。
    again = client.post(f"/api/v1/opml/import/{log_id}/undo")
    assert again.status_code == 409


def test_n018_undo_unknown_log_id_is_404(tree_client):
    client, _control = tree_client
    response = client.post("/api/v1/opml/import/999/undo")
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "opml_import_log_not_found"


def test_n018_tree_preview_endpoint_is_non_mutating(tree_client):
    client, control = tree_client
    response = client.post("/api/v1/opml/import/tree-preview", content=TREE_OPML)
    assert response.status_code == 200
    plan = response.json()
    assert plan["totalFeeds"] == 4
    assert len(plan["duplicateFeeds"]) == 2
    assert plan["createCategories"] == ["News"]
    assert len(plan["newFeeds"]) == 2
    # 预览零写。
    assert len(control.subscriptions) == 2
    assert len(control.categories) == 2


def test_n018_log_is_capped_at_five(tmp_path):
    db = Database(tmp_path / "log.sqlite")
    store = OpmlImportLogStore(db)
    for index in range(8):
        run(store.record(created_category_labels=[f"C{index}"], moved_feeds=[]))
    logs = run(store.list_recent())
    assert len(logs) == 5
    assert [log["createdCategoryLabels"] for log in logs] == [
        ["C7"],
        ["C6"],
        ["C5"],
        ["C4"],
        ["C3"],
    ]
