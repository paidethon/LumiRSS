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
from xml.sax.saxutils import quoteattr

import defusedxml.ElementTree as SafeET

from lumirss.adapters.freshrss import (
    CATEGORY_PREFIX,
    RESERVED_CATEGORY_LABEL,
    AdapterError,
)
from lumirss.adapters.freshrss_control import FreshRSSControlAdapter, InvalidFeedUrl

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


class OpmlService:
    """Preview (non-mutating) and merge-import over the control adapter."""

    def __init__(self, control: FreshRSSControlAdapter) -> None:
        self._control = control

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
