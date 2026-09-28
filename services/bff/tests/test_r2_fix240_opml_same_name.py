"""FIX-240 — OPML 同名分类（不同层级）flatten 后的映射一致性。

规则（文档化于 parse_opml / _build_tree_plan）：嵌套容器取**最外层**
真实标签（FreshRSS 单层分类模型，'/' 也不合法）——内层同名标签绝不
覆盖外层；不同父级/同级的同名文件夹 flatten 后归并到**同一个**
label → 预览聚合为一个分类、导入只建一次类并全部映射进它——预览与
实际映射一致，不存在互相覆盖。

基线排查结论：flat 路径（parse → _build_items → preview → import）对
同名分类已是一致的“同名归并”映射；tree 路径的计划文档声明“同名取
list_categories 顺序的第一个命中”（setdefault），而 tree_apply 的
label_to_id 字典推导是“最后命中”——上游 UNIQUE(name) 下两者不可达地
分叉，但本分支仍把 apply 钉在与计划相同的“首个命中”规则上（一致性
修复），并以测试固定。
"""

import asyncio

from lumirss.adapters.freshrss import RESERVED_CATEGORY_LABEL
from lumirss.adapters.freshrss_control import Category, Subscription
from lumirss.opml import OpmlService, parse_opml

OPML_SAME_NAME_LEVELS = b"""<?xml version="1.0"?>
<opml version="2.0"><body>
  <outline text="Tech">
    <outline text="Top Feed" xmlUrl="https://top.example/rss" />
  </outline>
  <outline text="News">
    <outline text="Tech">
      <outline text="Nested Feed" xmlUrl="https://nested.example/rss" />
    </outline>
  </outline>
  <outline text="Tech">
    <outline text="Sibling Feed" xmlUrl="https://sibling.example/rss" />
  </outline>
</body></opml>
"""


def run(coroutine):
    return asyncio.run(coroutine)


class FakeControlAdapter:
    def __init__(self) -> None:
        self.subscriptions: list[Subscription] = []
        self.categories: list[Category] = []
        self.next_id = 10
        self.created_labels: list[str] = []
        self.moves: list[tuple[str, str]] = []

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
        )
        self.subscriptions.append(subscription)
        return subscription

    async def move_category(self, stream_id, category_id):
        self.moves.append((stream_id, category_id))

    async def move_to_new_category(self, stream_id, label):
        self.created_labels.append(label)
        self.categories.append(Category(f"user/-/label/{label}", label))


def test_same_name_folders_at_different_levels_flatten_to_one_label():
    """flatten 规则 = 最外层真实标签胜出：News>Tech 嵌套里的内层同名
    「Tech」**不覆盖**外层「News」；顶层两处独立「Tech」文件夹归并到
    同一个 label（无互相覆盖）。"""
    parsed = parse_opml(OPML_SAME_NAME_LEVELS)
    assert [(entry.title, entry.category_label) for entry in parsed.entries] == [
        ("Top Feed", "Tech"),
        ("Nested Feed", "News"),  # 外层 News 胜出；内层同名 Tech 不覆盖
        ("Sibling Feed", "Tech"),
    ]


def test_preview_aggregates_same_name_into_one_category():
    """预览按 flatten 后的 label 聚合（Tech 两处归并为一行汇总），
    逐项 category 与 flatten 规则一致。"""
    fake = FakeControlAdapter()
    preview = run(OpmlService(fake).preview(OPML_SAME_NAME_LEVELS))
    assert preview["categories"] == [
        {"label": "News", "feedCount": 1},
        {"label": "Tech", "feedCount": 2},
    ]
    assert preview["newFeeds"] == 3
    by_title = {item["title"]: item for item in preview["items"]}
    assert by_title["Top Feed"]["category"] == "Tech"
    assert by_title["Nested Feed"]["category"] == "News"
    assert by_title["Sibling Feed"]["category"] == "Tech"
    assert all(item["status"] == "new" for item in preview["items"])


def test_import_maps_each_flattened_label_into_one_category():
    """导入：flatten 后每个 label 恰好创建一次分类（Tech 两处归并共用
    一个分类），结果与预览逐项一致。"""
    fake = FakeControlAdapter()
    result = run(OpmlService(fake).import_opml(OPML_SAME_NAME_LEVELS))
    assert sorted(fake.created_labels) == ["News", "Tech"], "每个 label 只建一次"
    tech_id = "user/-/label/Tech"
    tech_moves = [category_id for _stream, category_id in fake.moves]
    assert tech_moves.count(tech_id) == 1, "两处 Tech 分组共用同一分类"
    added = {entry["feedUrl"]: entry for entry in result["added"]}
    assert set(added) == {
        "https://top.example/rss",
        "https://nested.example/rss",
        "https://sibling.example/rss",
    }
    assert added["https://top.example/rss"]["categoryLabel"] == "Tech"
    assert added["https://nested.example/rss"]["categoryLabel"] == "News"
    assert added["https://sibling.example/rss"]["categoryLabel"] == "Tech"
    assert all(entry["categoryApplied"] is True for entry in added.values())


def test_flat_preview_categories_match_tree_plan_labels():
    """flat 预览与 tree 计划对同一文件给出同一分类集合（两条导入路径
    不分叉）。"""
    fake = FakeControlAdapter()
    flat = run(OpmlService(fake).preview(OPML_SAME_NAME_LEVELS))
    plan = run(OpmlService(fake).tree_preview(OPML_SAME_NAME_LEVELS))
    assert sorted(row["label"] for row in flat["categories"]) == sorted(
        plan["createCategories"]
    )
    assert RESERVED_CATEGORY_LABEL not in plan["createCategories"]
