"""OPML support for the subscription center (0013 Gate 4).

OPML files are UNTRUSTED XML:

- uploads are size-bounded (route reads the body with a hard cap before
  parsing anything);
- parsing goes through defusedxml (DTDs / entity expansion forbidden —
  no billion-laughs, no external entities);
- only the subscription-relevant subset is extracted: category outline
  containers and feed outlines (xmlUrl). Everything else is ignored.

Import is MERGE-ONLY: existing subscriptions are reported as duplicates
and never touched; nothing is unsubscribed, renamed or overwritten. Each
new feed is subscribed exactly once (the control adapter's semantics);
per-feed failures are collected and reported honestly instead of failing
the whole import.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from xml.sax.saxutils import quoteattr

import defusedxml.ElementTree as SafeET

from lumirss.adapters.freshrss import (
    CATEGORY_PREFIX,
    RESERVED_CATEGORY_LABEL,
    AdapterError,
)
from lumirss.adapters.freshrss_control import (
    FreshRSSControlAdapter,
    InvalidCategoryLabel,
    InvalidFeedUrl,
)
from lumirss.opml_import_log import OpmlImportLogStore

if TYPE_CHECKING:
    from lumirss.storage import Database

MAX_OPML_BYTES = 2 * 1024 * 1024  # aligned with the feed-preview bound
MAX_OPML_FEEDS = 500
MAX_OPML_DEPTH = 8  # outline nesting cap (body > folder > feed is depth 2)


class OpmlInvalid(AdapterError):
    """The file is not a well-formed OPML document."""


class OpmlTooLarge(AdapterError):
    """The uploaded OPML exceeds the size limit."""


class OpmlTooManyFeeds(AdapterError):
    """The OPML carries more feed outlines than the import limit allows."""


@dataclass
class OpmlEntry:
    """One feed outline (title may be empty; category None = uncategorized)."""

    title: str
    feed_url: str
    category_label: str | None = None


@dataclass
class ParsedOpml:
    entries: list[OpmlEntry] = field(default_factory=list)
    invalid_entries: int = 0  # outlines with an unusable xmlUrl
    invalid_items: list[OpmlEntry] = field(default_factory=list)
    # the same feed URL repeated inside the file (first occurrence wins):
    file_duplicates: list[OpmlEntry] = field(default_factory=list)

    @property
    def duplicate_count(self) -> int:
        return len(self.file_duplicates)


def _is_usable_feed_url(url: str) -> bool:
    """Same rule as the control adapter's subscribe path (http(s), bounded)."""
    try:
        FreshRSSControlAdapter._validate_feed_url(url)
    except InvalidFeedUrl:
        return False
    return True


def parse_opml(data: bytes) -> ParsedOpml:
    """Safely extract feed outlines + category labels from OPML bytes.

    Structure: <opml><body><outline text="Category"><outline text="Feed"
    xmlUrl="…"/></outline>…</body></opml>. Containers without a label are
    transparent (their feeds inherit the outer label); feeds directly under
    <body> are uncategorized. Repeated feed URLs keep the first occurrence.
    """
    if len(data) > MAX_OPML_BYTES:
        raise OpmlTooLarge("OPML file exceeds the 2 MiB limit.")
    try:
        root = SafeET.fromstring(data)
    except Exception as exc:
        raise OpmlInvalid("The file is not well-formed XML.") from exc
    if root.tag != "opml":
        raise OpmlInvalid("The file is not an OPML document (missing <opml> root).")
    body = root.find("body")
    if body is None:
        raise OpmlInvalid("OPML document has no <body>.")

    parsed = ParsedOpml()
    feed_outlines = 0

    def walk(element, category: str | None, depth: int) -> None:
        nonlocal feed_outlines
        if depth > MAX_OPML_DEPTH:
            raise OpmlInvalid("OPML outline nesting is too deep.")
        for outline in element.findall("outline"):
            xml_url = outline.get("xmlUrl")
            if xml_url is not None:
                feed_outlines += 1
                if feed_outlines > MAX_OPML_FEEDS:
                    raise OpmlTooManyFeeds(
                        "OPML carries more than 500 feed outlines."
                    )
                if not _is_usable_feed_url(xml_url):
                    parsed.invalid_entries += 1
                    # F002：逐项预览需要呈现不可用项（含原始 xmlUrl）
                    title = (outline.get("text") or outline.get("title") or "").strip()
                    parsed.invalid_items.append(
                        OpmlEntry(title=title, feed_url=xml_url, category_label=category)
                    )
                    continue
                title = (outline.get("text") or outline.get("title") or "").strip()
                parsed.entries.append(
                    OpmlEntry(title=title, feed_url=xml_url, category_label=category)
                )
            else:
                label = (outline.get("text") or outline.get("title") or "").strip()
                # Nested containers flatten onto the OUTERMOST real label.
                walk(outline, category if category is not None else (label or None), depth + 1)

    walk(body, None, 0)

    # Deduplicate by feed URL (first occurrence wins).
    seen: set[str] = set()
    deduped: list[OpmlEntry] = []
    for entry in parsed.entries:
        if entry.feed_url in seen:
            parsed.file_duplicates.append(entry)
        else:
            seen.add(entry.feed_url)
            deduped.append(entry)
    parsed.entries = deduped
    return parsed


def _failure_type(exc: AdapterError) -> str:
    """Stable short code for a per-feed import failure."""
    from lumirss.adapters.freshrss import (
        AuthenticationError,
        UpstreamConnectionError,
    )
    from lumirss.adapters.freshrss_control import FeedRejectedError

    if isinstance(exc, FeedRejectedError):
        return "feed_rejected"
    if isinstance(exc, UpstreamConnectionError):
        return "connection_error"
    if isinstance(exc, AuthenticationError):
        return "authentication_error"
    return "upstream_error"


def _label_applicable(label: str | None) -> bool:
    """N018：文件分类名能否映射到 FreshRSS 分类（非保留字且合法）。

    FreshRSS 分类 label 规则与 rename/create 相同（_validated_label：
    非空、无 '/'、≤128 字符）。不可用的 label → 订阅/移动仍执行，
    但分类不生效（与既有 category_conflict 语义一致，诚实汇报）。"""
    if label is None:
        return False
    try:
        clean = FreshRSSControlAdapter._validated_label(label)
    except InvalidCategoryLabel:
        return False
    return clean != RESERVED_CATEGORY_LABEL


class OpmlService:
    """Preview (non-mutating) and merge-import over the control adapter.

    N018：``db``（Lumi per-user 库）只在树对照 apply/undo 时用于撤销
    台账（opml_import_log）；flat 路径与预览路径零数据库写入。
    """

    def __init__(
        self,
        control: FreshRSSControlAdapter,
        db: "Database | None" = None,
    ) -> None:
        self._control = control
        self._db = db

    def _build_items(
        self, parsed: ParsedOpml, existing_urls: set[str]
    ) -> list[dict[str, object]]:
        """F002：逐项预览数组（preview 与 import 复用同一构造，索引稳定）。

        status: new | duplicate | invalid | category_conflict。
        duplicate = 已订阅或在文件内重复；category_conflict = 新源但分类
        保留字（导入会订阅成功但分类不生效）；invalid = xmlUrl 不可用。"""
        items: list[dict[str, object]] = []
        index = 0
        # 首次出现照常判定（new/duplicate/…）；文件内重复段整体标 duplicate
        for entry in parsed.entries:
            is_duplicate = entry.feed_url in existing_urls
            note = None
            if is_duplicate:
                status = "duplicate"
                note = "已订阅（或在文件内重复），导入时跳过"
            elif (entry.category_label or "").strip() == RESERVED_CATEGORY_LABEL:
                status = "category_conflict"
                note = (
                    f"分类「{entry.category_label}」为保留字，"
                    "订阅可导入但该分类不会生效（落入默认分类）"
                )
            else:
                status = "new"
            items.append(
                {
                    "index": index,
                    "title": entry.title,
                    "xmlUrl": entry.feed_url,
                    "category": entry.category_label,
                    "status": status,
                    "note": note,
                }
            )
            index += 1
        for entry in parsed.file_duplicates:
            items.append(
                {
                    "index": index,
                    "title": entry.title,
                    "xmlUrl": entry.feed_url,
                    "category": entry.category_label,
                    "status": "duplicate",
                    "note": "已订阅（或在文件内重复），导入时跳过",
                }
            )
            index += 1
        for entry in parsed.invalid_items:
            items.append(
                {
                    "index": index,
                    "title": entry.title,
                    "xmlUrl": entry.feed_url,
                    "category": entry.category_label,
                    "status": "invalid",
                    "note": "xmlUrl 不可用（非 http(s) 或超长）",
                }
            )
            index += 1
        return items

    def _parse_selected(
        self, selected_indexes: str | None
    ) -> set[int] | None:
        """解析 selected_indexes 查询参数（逗号分隔整数）。

        None/空 = 全部导入（向后兼容）；非法格式 → ValueError（路由 400）。"""
        if selected_indexes is None or selected_indexes.strip() == "":
            return None
        selected: set[int] = set()
        for chunk in selected_indexes.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if not chunk.lstrip("-").isdigit():
                raise ValueError(f"invalid index: {chunk!r}")
            selected.add(int(chunk))
        return selected

    async def preview(self, data: bytes) -> dict[str, object]:
        """Count what an import WOULD do — strictly read-only."""
        parsed = parse_opml(data)
        existing = {
            subscription.feed_url
            for subscription in await self._control.list_subscriptions()
        }
        new_feeds = 0
        duplicates = parsed.duplicate_count
        for entry in parsed.entries:
            if entry.feed_url in existing:
                duplicates += 1
            else:
                new_feeds += 1

        category_counts: dict[str, int] = {}
        for entry in parsed.entries:
            if entry.category_label is not None:
                category_counts[entry.category_label] = (
                    category_counts.get(entry.category_label, 0) + 1
                )
        return {
            "totalFeeds": len(parsed.entries),
            "newFeeds": new_feeds,
            "duplicates": duplicates,
            "invalidEntries": parsed.invalid_entries,
            "categories": [
                {"label": label, "feedCount": count}
                for label, count in sorted(category_counts.items())
            ],
            "items": self._build_items(parsed, existing),
        }

    async def import_opml(
        self, data: bytes, selected_indexes: set[int] | None = None
    ) -> dict[str, object]:
        """Merge-import: subscribe each selected NEW feed once, categorize it.

        Merge semantics — existing subscriptions are reported as duplicates
        and never modified. F002：selected_indexes（逐项预览的 index 集合）
        只影响哪些条目参与导入；None/空 = 全部（向后兼容）。未选中/重复/
        不可用的条目进入 skipped（诚实汇报跳过原因），不产生任何写。
        Category assignment happens per feed after the
        subscribe is server-confirmed: existing categories are reused, a
        missing one is created by the move itself (the only FreshRSS
        create-category channel, 0013 Gate 3). A failed category move never
        undoes the subscription — the feed stays in the default category and
        the result reports categoryApplied=false.
        """
        parsed = parse_opml(data)
        subscriptions = await self._control.list_subscriptions()
        existing_urls = {subscription.feed_url for subscription in subscriptions}
        items = self._build_items(parsed, existing_urls)
        label_to_id = {
            category.label: category.id
            for category in await self._control.list_categories()
        }

        added: list[dict[str, object]] = []
        duplicates: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []
        categories_created: list[str] = []

        def _duplicate(entry: OpmlEntry) -> dict[str, str]:
            return {"feedUrl": entry.feed_url, "title": entry.title or entry.feed_url}

        # in-file repeats share the fate of their first occurrence
        # （保持既有报告顺序：文件内重复先列，再列已订阅）
        file_dup_urls = {entry.feed_url for entry in parsed.file_duplicates}
        duplicates.extend(_duplicate(entry) for entry in parsed.file_duplicates)

        # F002：逐项选择；index 对应 _build_items 的稳定序
        selected: set[int] | None = selected_indexes

        for entry_index, item in enumerate(items):
            status = str(item["status"])
            feed_url = str(item["xmlUrl"])
            display_title = str(item["title"]) or feed_url
            entry = OpmlEntry(
                title=str(item["title"]),
                feed_url=feed_url,
                category_label=item["category"],  # type: ignore[arg-type]
            )

            if status == "invalid":
                if selected is None or entry_index in selected:
                    skipped.append(
                        {"feedUrl": feed_url, "title": display_title, "reason": "invalid"}
                    )
                continue

            if status == "duplicate":
                # in-file repeats were already reported above; existing
                # subscriptions are reported here (merge report, never written)
                if feed_url not in file_dup_urls:
                    duplicates.append(_duplicate(entry))
                if selected is not None and entry_index not in selected:
                    skipped.append(
                        {"feedUrl": feed_url, "title": display_title, "reason": "not_selected"}
                    )
                continue

            if selected is not None and entry_index not in selected:
                skipped.append(
                    {"feedUrl": feed_url, "title": display_title, "reason": "not_selected"}
                )
                continue

            if feed_url in existing_urls:
                duplicates.append(_duplicate(entry))
                continue

            try:
                subscription = await self._control.subscribe(
                    entry.feed_url, title=entry.title or None
                )
            except AdapterError as exc:
                failed.append(
                    {
                        "feedUrl": entry.feed_url,
                        "title": display_title,
                        "error": _failure_type(exc),
                    }
                )
                continue
            existing_urls.add(entry.feed_url)

            label = (entry.category_label or "").strip()
            category_applied = False
            if label and label != RESERVED_CATEGORY_LABEL:
                try:
                    target_id = label_to_id.get(label)
                    if target_id is None:
                        await self._control.move_to_new_category(
                            subscription.stream_id, label
                        )
                        # greader contract: the created category's id is
                        # derived from its label (verified in Gate 1/3).
                        target_id = f"{CATEGORY_PREFIX}{label}"
                        categories_created.append(label)
                    else:
                        await self._control.move_category(
                            subscription.stream_id, target_id
                        )
                    label_to_id[label] = target_id
                    category_applied = True
                except AdapterError:
                    category_applied = False  # stays in the default category

            added.append(
                {
                    "feedUrl": entry.feed_url,
                    "title": subscription.title,
                    "categoryLabel": label or None,
                    "categoryApplied": category_applied,
                }
            )

        return {
            "added": added,
            "duplicates": duplicates,
            "failed": failed,
            "skipped": skipped,
            "categoriesCreated": categories_created,
        }

    # ---- N018 树对照导入 -----------------------------------------------------

    @staticmethod
    def _tree_label_of(entry: OpmlEntry) -> str | None:
        """条目的有效分类名（保留字/非法 label → None，同 flat 导入口径）。"""
        label = (entry.category_label or "").strip()
        return label if _label_applicable(label) else None

    def _build_tree_plan(
        self,
        parsed: ParsedOpml,
        subscriptions: list,
        categories: list,
    ) -> dict[str, object]:
        """N018：OPML 分类对照当前 FreshRSS 分类 → 计划（严格只读）。

        确定性规则（文档化）：
        - 分类重名：按名字精确匹配、取 list_categories 顺序的**第一个**
          命中复用（FreshRSS tag/list folder 名唯一；若上游出现重名，
          首个命中是稳定规则）；
        - OPML 层级映射到**最外层**容器标签（既有 flatten 规则）：
          FreshRSS 是单层分类模型，且 '/' 不是合法分类名字符，嵌套
          层级无法原样表达；
        - 已订阅 feed（duplicate）策略：目标分类与当前不同 → action
          ``update``（计划移动到文件的分类）；已在目标分类或文件条目
          无有效分类 → action ``skip``（绝不擅自移动到「无分类」——
          默认分类不可经 greader API 定位，见 DefaultCategoryImmutable）。
        """
        subscriptions = list(subscriptions)
        categories = list(categories)
        existing_by_label: dict[str, str] = {}
        for category in categories:
            existing_by_label.setdefault(category.label, category.id)

        file_labels: list[str] = []
        for entry in parsed.entries:
            label = self._tree_label_of(entry)
            if label is not None and label not in file_labels:
                file_labels.append(label)

        create_categories = [
            label for label in file_labels if label not in existing_by_label
        ]
        reuse_categories = [
            label for label in file_labels if label in existing_by_label
        ]

        by_url = {subscription.feed_url: subscription for subscription in subscriptions}
        move_feeds: list[dict[str, object]] = []
        duplicate_feeds: list[dict[str, object]] = []
        new_feeds: list[dict[str, object]] = []
        invalid_entries = parsed.invalid_entries
        for entry in parsed.entries:
            label = self._tree_label_of(entry)
            subscription = by_url.get(entry.feed_url)
            if subscription is None:
                new_feeds.append(
                    {
                        "feedUrl": entry.feed_url,
                        "title": entry.title or entry.feed_url,
                        "categoryLabel": label,
                    }
                )
                continue
            current_label = subscription.category_label
            if label is not None and label != current_label:
                action = "update"
                target_id = existing_by_label.get(label) or f"{CATEGORY_PREFIX}{label}"
                move_feeds.append(
                    {
                        "feed": entry.feed_url,
                        "from": current_label,
                        "to": label,
                        "toCategoryId": target_id,
                        "subscriptionRef": subscription.subscription_ref,
                    }
                )
            else:
                action = "skip"
            duplicate_feeds.append(
                {
                    "feed": entry.feed_url,
                    "title": entry.title or subscription.title or entry.feed_url,
                    "action": action,
                }
            )
        return {
            "totalFeeds": len(parsed.entries),
            "newFeeds": new_feeds,
            "invalidEntries": invalid_entries,
            "createCategories": create_categories,
            "reuseCategories": reuse_categories,
            "moveFeeds": move_feeds,
            "duplicateFeeds": duplicate_feeds,
            "notes": [
                "分类重名按名字精确匹配、复用既有分类（首个命中，确定性规则）。",
                "OPML 嵌套层级映射到最外层容器标签（FreshRSS 单层分类模型）。",
                "新建分类由移动 feed 产生（FreshRSS 仅支持该建类路径）；"
                "没有 feed 落入的文件分类不会被创建。",
                "已订阅 feed 的默认策略：分类不同则移动（update），一致则跳过（skip）。",
            ],
        }

    async def tree_preview(self, data: bytes) -> dict[str, object]:
        """N018 树对照预览——严格只读（不订阅、不移动、不建类）。"""
        parsed = parse_opml(data)
        subscriptions = await self._control.list_subscriptions()
        categories = await self._control.list_categories()
        return self._build_tree_plan(parsed, subscriptions, categories)

    async def tree_apply(self, data: bytes) -> dict[str, object]:
        """N018 树对照应用：按计划订阅新 feed + 移动既有 feed（建类随行）。

        执行语义与预览一致但**以执行时刻的服务器状态为准**（预览是
        建议，不是陈旧契约）。每次执行写一行 opml_import_log（新建
        分类名 + 被移动 feed，cap 5）供 undo；只有 create/move 类
        变更入账，skip 从不入账。
        """
        parsed = parse_opml(data)
        subscriptions = await self._control.list_subscriptions()
        categories = await self._control.list_categories()
        existing_urls = {subscription.feed_url for subscription in subscriptions}
        label_to_id = {category.label: category.id for category in categories}

        added: list[dict[str, object]] = []
        moved: list[dict[str, object]] = []
        skipped: list[dict[str, object]] = []
        failed: list[dict[str, object]] = []
        categories_created: list[str] = []

        async def _place(
            stream_id: str, feed_url: str, label: str | None
        ) -> tuple[bool, str | None]:
            """把 feed 放入文件分类；返回 (applied, createdLabel)。"""
            if label is None:
                return False, None
            target_id = label_to_id.get(label)
            try:
                if target_id is None:
                    await self._control.move_to_new_category(stream_id, label)
                    # greader contract: created category id derives from label.
                    label_to_id[label] = f"{CATEGORY_PREFIX}{label}"
                    return True, label
                await self._control.move_category(stream_id, target_id)
                return True, None
            except AdapterError as exc:
                failed.append(
                    {"feedUrl": feed_url, "kind": "category", "error": _failure_type(exc)}
                )
                return False, None

        for entry in parsed.entries:
            label = self._tree_label_of(entry)
            if entry.feed_url in existing_urls:
                subscription = next(
                    (
                        sub
                        for sub in subscriptions
                        if sub.feed_url == entry.feed_url
                    ),
                    None,
                )
                if subscription is None:  # 并发退订：按 skip 诚实汇报
                    skipped.append({"feedUrl": entry.feed_url, "reason": "vanished"})
                    continue
                if label is not None and label != subscription.category_label:
                    # 先取迁移前快照：适配器返回的对象不代表迁移后的状态。
                    from_id = subscription.category_id
                    applied, created = await _place(
                        subscription.stream_id, entry.feed_url, label
                    )
                    if applied:
                        moved.append(
                            {
                                "streamId": subscription.stream_id,
                                "feedUrl": entry.feed_url,
                                "fromCategoryId": from_id,
                                "toCategoryId": label_to_id.get(label),
                            }
                        )
                        if created is not None:
                            categories_created.append(created)
                else:
                    skipped.append({"feedUrl": entry.feed_url, "reason": "already_in_place"})
                continue
            try:
                subscription = await self._control.subscribe(
                    entry.feed_url, title=entry.title or None
                )
            except AdapterError as exc:
                failed.append(
                    {"feedUrl": entry.feed_url, "kind": "subscribe", "error": _failure_type(exc)}
                )
                continue
            existing_urls.add(entry.feed_url)
            subscriptions.append(subscription)
            applied, created = await _place(
                subscription.stream_id, entry.feed_url, label
            )
            if created is not None:
                categories_created.append(created)
            added.append(
                {
                    "feedUrl": entry.feed_url,
                    "title": subscription.title,
                    "categoryLabel": label,
                    "categoryApplied": applied,
                }
            )

        log_id = 0
        if self._db is not None:
            log_id = await OpmlImportLogStore(self._db).record(
                created_category_labels=categories_created,
                moved_feeds=moved,
            )
        return {
            "logId": log_id,
            "added": added,
            "moved": moved,
            "skipped": skipped,
            "failed": failed,
            "categoriesCreated": sorted(set(categories_created)),
        }

    async def undo_import(self, log_id: int) -> dict[str, object]:
        """N018：撤销一次树对照导入（feed 移回原分类 + 诚实建类边界）。

        - 被移动的 feed：移回原分类（原分类仍存在且 feed 仍订阅时）；
          原分类已消失 / feed 已退订 → 逐项如实汇报原因，绝不臆造；
        - 新建分类：FreshRSS greader API **没有**分类删除端点（适配层
          只有 subscribe/unsubscribe/move/rename，已核实），因此空分类
          无法经本接口删除——如实列为 categoriesNotDeleted，可在
          FreshRSS 原生界面清理；
        - 每行至多撤销一次（undone_at 记账）。
        """
        from lumirss.opml_import_log import OpmlImportLogStore

        entry = await OpmlImportLogStore(self._db).get(log_id)
        # 已撤销行 → OpmlImportLogUndone；不存在 → OpmlImportLogNotFound。
        await OpmlImportLogStore(self._db).mark_undone(log_id)

        categories = {category.id: category for category in await self._control.list_categories()}
        subscriptions = {sub.stream_id: sub for sub in await self._control.list_subscriptions()}
        moved_back: list[dict[str, object]] = []
        not_restored: list[dict[str, object]] = []
        for item in entry["movedFeeds"]:
            stream_id = str(item.get("streamId") or "")
            from_id = item.get("fromCategoryId")
            feed_url = str(item.get("feedUrl") or stream_id)
            subscription = subscriptions.get(stream_id)
            if subscription is None:
                not_restored.append({"feedUrl": feed_url, "reason": "unsubscribed"})
                continue
            if not from_id or from_id not in categories:
                not_restored.append({"feedUrl": feed_url, "reason": "category_gone"})
                continue
            try:
                await self._control.move_category(stream_id, str(from_id))
            except AdapterError as exc:
                not_restored.append(
                    {"feedUrl": feed_url, "reason": "upstream_error", "error": _failure_type(exc)}
                )
                continue
            moved_back.append({"feedUrl": feed_url, "toCategoryId": from_id})

        return {
            "logId": log_id,
            "movedBack": moved_back,
            "notRestored": not_restored,
            "categoriesDeleted": [],
            "categoriesNotDeleted": [
                {"label": label, "reason": "greader_api_no_delete"}
                for label in entry["createdCategoryLabels"]
            ],
            "note": (
                "FreshRSS greader API 无分类删除端点：空出的新建分类留在实例中，"
                "可在 FreshRSS 原生界面清理。"
            ),
        }

    async def export_selected(
        self,
        subscription_refs: list[str] | None = None,
        category_ids: list[str] | None = None,
    ) -> bytes:
        """F003：按所选导出 OPML（缺省参数 = 全库，走上游透传）。

        只包含选中集合的订阅与它们的分类结构（分类容器原样保留，空分类
        不导出；未分组 feed 直接放 body 下）。标题/URL 全部经 XML 转义；
        无效 subscriptionRef 直接拒绝（400），不静默吞掉。"""
        from lumirss.subscriptionref import (
            InvalidSubscriptionReference,
            decode_subscription_ref,
        )

        subscriptions = await self._control.list_subscriptions()
        ref_set = set(subscription_refs or [])
        category_set = set(category_ids or [])
        selected = [
            subscription
            for subscription in subscriptions
            if (not ref_set and not category_set)
            or (subscription.subscription_ref in ref_set if ref_set else False)
            or (
                subscription.category_id in category_set
                if category_set and subscription.category_id is not None
                else False
            )
        ]
        # 显式请求的 subscriptionRef 必须都能解析且命中，否则 400
        for ref in ref_set:
            try:
                decode_subscription_ref(ref)
            except InvalidSubscriptionReference as exc:
                raise OpmlInvalid(f"无效的 subscriptionRef：{ref}") from exc
            if not any(s.subscription_ref == ref for s in subscriptions):
                raise OpmlInvalid(f"subscriptionRef 不存在：{ref}")

        # 分类结构：label → feeds；未分组单独一组
        grouped: dict[str, list[object]] = {}
        ungrouped: list[object] = []
        labels: dict[str, str] = {}
        for subscription in selected:
            if subscription.category_id is not None and subscription.category_label:
                label = subscription.category_label
                labels[subscription.category_id] = label
                grouped.setdefault(subscription.category_id, []).append(subscription)
            else:
                ungrouped.append(subscription)

        def feed_line(subscription: object) -> str:
            title = getattr(subscription, "title", "") or getattr(
                subscription, "feed_url", ""
            )
            url = getattr(subscription, "feed_url", "")
            return f"    <outline text={quoteattr(title)} xmlUrl={quoteattr(url)} />"

        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<opml version="2.0">',
            "  <head><title>LumiRSS selected subscriptions</title></head>",
            "  <body>",
        ]
        for category_id in sorted(grouped):
            label = labels[category_id]
            lines.append(f"  <outline text={quoteattr(label)}>")
            for subscription in grouped[category_id]:
                lines.append(feed_line(subscription))
            lines.append("  </outline>")
        for subscription in ungrouped:
            lines.append(feed_line(subscription))
        lines.append("  </body>")
        lines.append("</opml>")
        text = "\n".join(lines) + "\n"
        return text.encode("utf-8")
