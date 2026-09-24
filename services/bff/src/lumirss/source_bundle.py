"""N011 来源组合包 — credential-free source bundle export / import.

A bundle is a portable JSON document of SOURCE IDENTITY ONLY:

    {"version": 1, "sources": [{"feed_url", "title", "category", "type"}]}

Export never copies credentials. Lumi-generated feeds (API sources,
mail bridges) are subscribed by FreshRSS under Atom URLs that EMBED the
per-source secret — exporting those URLs verbatim would leak a live
credential into a portable file, so they are sanitized to stable URNs
(``urn:lumirss:api-source:<uuid>`` / ``urn:lumirss:mail:<uuid>``).

Import is preview-by-default (``?apply=true`` commits). RSS rows are
subscribed through the same control path as OPML import (merge-only:
existing subscriptions report ``exists`` and are never modified). Rows
whose type needs credentials cannot be revived from a bundle — they
import as DISABLED drafts in the staging pool so the operator can
re-create them deliberately. Re-importing the same bundle is idempotent:
every already-present row reports ``exists`` again.
"""

import re
from typing import Any

from lumirss.adapters.freshrss import CATEGORY_PREFIX, AdapterError
from lumirss.staged_source_store import StagedSourceStore
from lumirss.util import utc_now

BUNDLE_VERSION = 1
MAX_BUNDLE_SOURCES = 500
MAX_URL_LENGTH = 2048
MAX_TITLE_LENGTH = 300
MAX_CATEGORY_LENGTH = 64

_URN_API = re.compile(r"^urn:lumirss:api-source:([0-9a-fA-F-]{36})$")
_URN_MAIL = re.compile(r"^urn:lumirss:mail:([0-9a-fA-F-]{36})$")

_NEEDS_CREDENTIALS = {"api", "mail", "inbox"}


class BundleInvalid(Exception):
    """The bundle document failed structural validation (400 stable)."""


def _clean_text(value: object, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _validate_source_entry(entry: Any, index: int) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise BundleInvalid(f"sources[{index}] 必须是对象。")
    feed_url = _clean_text(entry.get("feed_url"), MAX_URL_LENGTH)
    if not feed_url:
        raise BundleInvalid(f"sources[{index}].feed_url 不能为空。")
    source_type = _clean_text(entry.get("type"), 16) or "rss"
    if source_type not in _NEEDS_CREDENTIALS | {"rss"}:
        raise BundleInvalid(f"sources[{index}].type 不合法：{source_type!r}")
    category = _clean_text(entry.get("category"), MAX_CATEGORY_LENGTH) or None
    return {
        "feed_url": feed_url,
        "title": _clean_text(entry.get("title"), MAX_TITLE_LENGTH),
        "category": category,
        "type": source_type,
        "notes": _clean_text(entry.get("notes"), 500) or None,
    }


def validate_bundle(payload: Any) -> list[dict[str, Any]]:
    """Structural gate: version 1, ≤500 unique source rows."""
    if not isinstance(payload, dict):
        raise BundleInvalid("组合包必须是 JSON 对象。")
    if payload.get("version") != BUNDLE_VERSION:
        raise BundleInvalid(f"组合包版本必须是 {BUNDLE_VERSION}。")
    sources = payload.get("sources")
    if not isinstance(sources, list):
        raise BundleInvalid("组合包缺少 sources 数组。")
    if len(sources) > MAX_BUNDLE_SOURCES:
        raise BundleInvalid(f"组合包来源数超过 {MAX_BUNDLE_SOURCES}。")
    cleaned = [_validate_source_entry(entry, i) for i, entry in enumerate(sources)]
    seen: set[str] = set()
    for entry in cleaned:
        if entry["feed_url"] in seen:
            raise BundleInvalid(f"组合包内重复的 feed_url：{entry['feed_url']}")
        seen.add(entry["feed_url"])
    return cleaned


def sanitize_feed_url(feed_url: str, source_type: str, source_uuid: str | None) -> str:
    """Credential-free bundle URL for a Lumi-generated feed."""
    if source_type == "api" and source_uuid:
        return f"urn:lumirss:api-source:{source_uuid}"
    if source_type == "mail" and source_uuid:
        return f"urn:lumirss:mail:{source_uuid}"
    return feed_url


class SourceBundleService:
    """Export + preview/apply import over the control adapter."""

    def __init__(self, control, db) -> None:
        self._control = control
        self._db = db
        self._staged = StagedSourceStore(db)

    async def export_bundle(self, feed_urls: list[str]) -> dict[str, Any]:
        """Project the requested subscriptions into a bundle document.

        Type detection happens against Lumi's OWN stores (api source uuid
        prefix / mail uuid prefix in the URL path); everything else is a
        plain RSS feed. Requested URLs that match no subscription land in
        ``missing`` — honest, no fabrication."""
        from lumirss.api_source_store import ApiSourceStore
        from lumirss.mail_bridge import MailBridgeStore

        subscriptions = await self._control.list_subscriptions()
        by_url = {subscription.feed_url: subscription for subscription in subscriptions}
        api_rows = {row.uuid: row for row in await ApiSourceStore(self._db).list_sources()}
        mail_rows = {row.uuid: row for row in await MailBridgeStore(self._db).list_lists()}

        sources: list[dict[str, Any]] = []
        missing: list[str] = []
        for url in dict.fromkeys(feed_urls):  # dedupe, keep order
            subscription = by_url.get(url)
            if subscription is None:
                missing.append(url)
                continue
            source_type, source_uuid = _classify(url, api_rows, mail_rows)
            sources.append(
                {
                    "feed_url": sanitize_feed_url(url, source_type, source_uuid),
                    "title": subscription.title or "",
                    "category": subscription.category_label,
                    "type": source_type,
                }
            )
        return {
            "version": BUNDLE_VERSION,
            "generatedAt": utc_now(),
            "sources": sources,
            "missing": missing,
        }

    async def preview(self, payload: Any) -> dict[str, Any]:
        """Read-only per-item verdict; nothing subscribes, nothing stores."""
        entries = validate_bundle(payload)
        return await self._plan(entries, apply=False)

    async def apply(self, payload: Any) -> dict[str, Any]:
        """Commit: subscribe RSS rows once, store credential drafts."""
        entries = validate_bundle(payload)
        return await self._plan(entries, apply=True)

    async def _plan(self, entries: list[dict[str, Any]], *, apply: bool) -> dict[str, Any]:
        subscriptions = await self._control.list_subscriptions()
        existing_urls = {subscription.feed_url for subscription in subscriptions}
        label_to_id = {
            category.label: category.id
            for category in await self._control.list_categories()
        }
        items: list[dict[str, Any]] = []
        counts = {"new": 0, "exists": 0, "needs_credentials": 0, "invalid": 0, "failed": 0}
        for entry in entries:
            feed_url = str(entry["feed_url"])
            urn_kind = _urn_kind(feed_url)
            source_type = str(entry["type"])
            needs_credentials = source_type in _NEEDS_CREDENTIALS or urn_kind is not None
            label = entry["category"]
            if needs_credentials:
                status = "needs_credentials"
                category_action = "none"
                note = (
                    "该类型来源的凭据不会随组合包携带：导入为停用草稿，需在 Lumi 中重建后重新订阅。"
                    if apply
                    else "导入时将成为停用草稿（凭据不随组合包携带）。"
                )
                if apply:
                    try:
                        await self._staged.add(
                            url=feed_url,
                            title=str(entry["title"]),
                            note=note,
                            source_type=urn_kind or source_type,
                            origin="bundle_draft",
                        )
                    except Exception:  # noqa: BLE001 — duplicate draft → exists
                        status = "exists"
                        note = "草稿已存在（幂等导入）。"
            elif not feed_url.startswith(("http://", "https://")):
                status = "invalid"
                category_action = "none"
                note = "feed_url 不是可订阅的 http(s) 地址。"
            elif feed_url in existing_urls:
                status = "exists"
                category_action = _category_action(label, label_to_id)
                note = None
            else:
                status = "new"
                category_action = _category_action(label, label_to_id)
                note = None
            counts[status] = counts.get(status, 0) + 1
            items.append(
                {
                    "feedUrl": feed_url,
                    "title": str(entry["title"]),
                    "status": status,
                    "type": source_type,
                    "categoryAction": category_action,
                    "note": note,
                }
            )
            if apply and status == "new":
                subscribed = await self._subscribe_one(entry, label, label_to_id)
                if subscribed:
                    existing_urls.add(feed_url)
                else:
                    items[-1]["status"] = "failed"
                    items[-1]["note"] = "FreshRSS 拒绝该订阅，未导入。"
                    counts["new"] -= 1
                    counts["failed"] += 1
        return {
            "items": items,
            "counts": counts,
            "applied": apply,
            "imported": None,
        }

    async def _subscribe_one(
        self, entry: dict[str, Any], label: str | None, label_to_id: dict[str, str]
    ) -> bool:
        """Same merge semantics as OPML import: subscribe once, then move
        to the named category (creating it via the move when missing)."""
        feed_url = str(entry["feed_url"])
        title = str(entry["title"]) or None
        try:
            subscription = await self._control.subscribe(feed_url, title=title)
        except AdapterError:
            return False
        label = (label or "").strip()
        if label:
            try:
                target_id = label_to_id.get(label)
                if target_id is None:
                    await self._control.move_to_new_category(subscription.stream_id, label)
                    label_to_id[label] = f"{CATEGORY_PREFIX}{label}"
                else:
                    await self._control.move_category(subscription.stream_id, target_id)
            except AdapterError:
                pass  # subscription stands; category stays default (honest per-item note)
        return True


def _classify(
    feed_url: str,
    api_rows: dict[str, Any],
    mail_rows: dict[str, Any],
) -> tuple[str, str | None]:
    """Detect Lumi-generated feeds by uuid path segment (secrets are
    hashed in storage, so matching uses the uuid prefix only)."""
    from urllib.parse import urlsplit

    path = urlsplit(feed_url).path
    if path.startswith("/feeds/mail/"):
        for uuid in mail_rows:
            if path.startswith(f"/feeds/mail/{uuid}."):
                return "mail", uuid
    if path.startswith("/feeds/"):
        for uuid in api_rows:
            if path.startswith(f"/feeds/{uuid}."):
                return "api", uuid
    return "rss", None


def _urn_kind(feed_url: str) -> str | None:
    if _URN_API.match(feed_url):
        return "api"
    if _URN_MAIL.match(feed_url):
        return "mail"
    return None


def _category_action(label: str | None, label_to_id: dict[str, str]) -> str:
    """Preview-only hint: what applying this row would do to categories."""
    if not (label or "").strip():
        return "none"
    if label in label_to_id:
        return "reuse"
    return "create"
