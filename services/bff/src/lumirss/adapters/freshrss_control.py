"""FreshRSSControlAdapter — subscription/category control plane (0013).

Translates the FreshRSS Google Reader *management* endpoints
(subscription/edit, rename-tag, subscription/list, tag/list) into stable
LumiRSS operations:

    subscribe / unsubscribe / move category / rename category

Credential, ClientLogin auth-token and action-token state are NOT owned
here: the adapter is constructed over a shared ``FreshRSSSession`` (the
same instance the read-path FreshRSSAdapter uses), so login state is never
duplicated (0013 Gate 1 constraint).

FreshRSS 1.29.1 behaviors this adapter is built on (source + live probe,
2026-08-31):

- subscription/edit: POST form (``s``, ``ac``, optional ``t``/``a``/``r``).
  The ``T`` action token is IGNORED by this endpoint (neither required nor
  validated — legacy clients are tolerated); we still send it per the
  greader protocol. Success is HTTP 200 + body "OK".
  - ac=subscribe: ``s=feed/<url>``; ``t`` sets the title, ``a`` sets the
    category (auto-created when missing; the empty/“Uncategorized”/
    localized default names all map to the default category). Duplicate
    subscription or a feed FreshRSS cannot add → 400 "Bad Request!".
  - ac=unsubscribe: ``s=feed/<id>`` (numeric id) or ``feed/<url>``;
    unknown feed → 400.
  - ac=edit: ``s=feed/<id>``; ``a=user/-/label/<名>`` moves the feed
    (category auto-created when missing), ``t`` renames the feed title
    (feed-title rename is out of Lumi scope, 0013). Unknown feed → 400.
- rename-tag: POST form (``s``, ``dest``, ``T`` — T IS validated here;
  garbage → 401 + ``Google-Bad-Token: true``). Renames a category by DB
  name (falls back to user tags, which Lumi never touches). Source or dest
  not shaped ``user/-/label/<名>`` → 400; source not found → 400.
  Traps verified live:
  - Renaming the DEFAULT category via its API-visible (localized) id is
    impossible: the DAO forces the default category's display name to the
    localized string, so ``searchByName(<localized>)`` finds nothing → 400.
    (And even a DB-level rename would be invisible: display re-localizes.)
  - rename-tag to a colliding name can return "OK" while silently doing
    nothing (UNIQUE(name) / same-named tag blocks the SQL UPDATE, result
    unchecked) — hence the mandatory post-check here.
- tag/list: GET; ``type: "folder"`` entries are the categories
  (``user/-/label/<名>``); user tags have ``type: "tag"``; the rest are
  state pseudo-tags. This is the only endpoint that lists empty categories.
- subscription/list: ``id: "feed/<N>"`` is the upstream stream id — the
  payload for Lumi's opaque subscriptionRef.

Mutation safety: every mutation is attempted exactly once. A 401 retry
(re-login once, retry once) is safe because FreshRSS checks auth BEFORE
any mutation logic. Timeouts/connection failures are NEVER retried here —
callers re-read server state and reconcile instead.
"""

import urllib.parse

import httpx

from lumirss.adapters.freshrss import (
    AdapterError,
    AuthenticationError,
    FreshRSSSession,
    UpstreamError,
)
from lumirss.subscriptionref import (
    InvalidSubscriptionReference,
    encode_subscription_ref,
)

_CATEGORY_PREFIX = "user/-/label/"
# Bound on the proxied OPML export body (defensive; FreshRSS instances are
# single-user and far below this).
_MAX_OPML_EXPORT_BYTES = 10 * 1024 * 1024
# Default category's DB name (FreshRSS_CategoryDAO::DEFAULT_CATEGORY_NAME);
# reserving it as a rename destination avoids the silent-no-op / duplicate
# label traps above. This is a fixed upstream constant, not a UI-localized
# string.
_RESERVED_CATEGORY_LABEL = "Uncategorized"
# Bound on the proxied OPML export body (defensive; single-user
# FreshRSS instances are far below this).
_MAX_OPML_EXPORT_BYTES = 10 * 1024 * 1024
_MAX_LABEL_LENGTH = 128
_MAX_FEED_URL_LENGTH = 2048


class InvalidFeedUrl(AdapterError):
    """The feed URL is not a usable http(s) URL."""


class SubscriptionConflict(AdapterError):
    """A subscription with this feed URL already exists."""


class FeedRejectedError(AdapterError):
    """FreshRSS refused to add the feed (invalid or unreachable URL)."""


class SubscriptionNotFound(AdapterError):
    """The stream id is well-formed but FreshRSS has no such subscription."""


class InvalidCategoryReference(AdapterError):
    """categoryId is not a well-formed user/-/label/<名> reference."""


class InvalidCategoryLabel(AdapterError):
    """The requested category label is empty, contains '/', or is too long."""


class CategoryNotFound(AdapterError):
    """The category reference is well-formed but FreshRSS has no such category."""


class CategoryLabelConflict(AdapterError):
    """Another category (or the reserved default name) already uses the label."""


class DefaultCategoryImmutable(AdapterError):
    """FreshRSS's default category cannot be renamed through the greader API."""


class Subscription:
    """Management view of one FreshRSS subscription (0013).

    ``stream_id`` is the upstream ``feed/<N>`` id; ``subscription_ref`` is
    the Lumi-owned opaque reference built from it (never exposed raw).
    """

    def __init__(
        self,
        stream_id: str,
        title: str,
        feed_url: str,
        category_id: str | None = None,
        category_label: str | None = None,
    ) -> None:
        self.stream_id = stream_id
        self.title = title
        self.feed_url = feed_url
        self.category_id = category_id
        self.category_label = category_label

    @property
    def subscription_ref(self) -> str:
        return encode_subscription_ref(self.stream_id)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Subscription)
            and self.stream_id == other.stream_id
            and self.title == other.title
            and self.feed_url == other.feed_url
            and self.category_id == other.category_id
            and self.category_label == other.category_label
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"Subscription(stream_id={self.stream_id!r}, title={self.title!r}, "
            f"feed_url={self.feed_url!r}, category_id={self.category_id!r}, "
            f"category_label={self.category_label!r})"
        )


class Category:
    """One FreshRSS category (single-category model: a feed has exactly one)."""

    def __init__(self, category_id: str, label: str) -> None:
        self.id = category_id
        self.label = label

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Category)
            and self.id == other.id
            and self.label == other.label
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"Category(id={self.id!r}, label={self.label!r})"


class FreshRSSControlAdapter:
    """Control-plane operations over the SHARED FreshRSS session."""

    def __init__(self, session: FreshRSSSession) -> None:
        self._session = session

    async def list_subscriptions(self) -> list[Subscription]:
        """All subscriptions with their upstream feed ids and categories."""
        payload = await self._with_auth_retry(
            lambda: self._session._authorized_get_json(
                "reader/api/0/subscription/list", {"output": "json"}
            )
        )
        subscriptions: list[Subscription] = []
        for item in self._iter_list(payload, "subscription/list", "subscriptions"):
            stream_id = item.get("id")
            title = item.get("title")
            url = item.get("url")
            if not (
                isinstance(stream_id, str)
                and isinstance(title, str)
                and isinstance(url, str)
            ):
                raise UpstreamError(
                    "FreshRSS subscription entry missing 'id', 'title' or 'url'."
                )
            category_id, category_label = self._category_of(item)
            subscriptions.append(
                Subscription(
                    stream_id=stream_id,
                    title=title,
                    feed_url=url,
                    category_id=category_id,
                    category_label=category_label,
                )
            )
        return subscriptions

    async def list_categories(self) -> list[Category]:
        """All categories (including empty ones) via tag/list folders."""
        payload = await self._with_auth_retry(
            lambda: self._session._authorized_get_json(
                "reader/api/0/tag/list", {"output": "json"}
            )
        )
        categories: list[Category] = []
        for item in self._iter_list(payload, "tag/list", "tags"):
            if item.get("type") != "folder":
                continue  # user tags and state pseudo-tags are not categories
            category_id = item.get("id")
            if not isinstance(category_id, str) or not category_id.startswith(
                _CATEGORY_PREFIX
            ):
                raise UpstreamError("FreshRSS tag/list folder has an unexpected id.")
            categories.append(
                Category(category_id=category_id, label=category_id[len(_CATEGORY_PREFIX):])
            )
        return categories

    async def subscribe(
        self,
        feed_url: str,
        *,
        category_id: str | None = None,
        title: str | None = None,
    ) -> Subscription:
        """Subscribe to a feed URL (optionally into a category, with a title).

        Server-confirmed: after FreshRSS accepts the write, the new
        subscription is re-read from subscription/list and returned; if it
        is not visible the call fails (no half-confirmed success).
        """
        self._validate_feed_url(feed_url)
        if category_id is not None:
            self._validate_category_id(category_id)
        title = title.strip() if title is not None else None
        if not title:
            title = None  # blank → absent: the feed's own title is used

        existing = await self.list_subscriptions()
        for subscription in existing:
            if subscription.feed_url == feed_url:
                raise SubscriptionConflict("Already subscribed to this feed URL.")
        if category_id is not None:
            await self._require_category(category_id)

        fields: list[tuple[str, str]] = [("ac", "subscribe"), ("s", f"feed/{feed_url}")]
        if title is not None:
            fields.append(("t", title))
        if category_id is not None:
            fields.append(("a", category_id))
        response = await self._with_auth_retry(
            lambda: self._post_subscription_edit(fields)
        )
        self._require_ok(response, on_bad_request=FeedRejectedError(
            "FreshRSS refused to add this feed (invalid or unreachable URL)."
        ))

        # Server-confirmed success: re-read and match by feed URL.
        for subscription in await self.list_subscriptions():
            if subscription.feed_url == feed_url:
                return subscription
        raise UpstreamError(
            "FreshRSS accepted the subscription but it is not visible."
        )

    async def unsubscribe(self, stream_id: str) -> None:
        """Remove one subscription (by its upstream feed/<N> stream id)."""
        self._validate_stream_id(stream_id)
        await self._require_subscription(stream_id)
        response = await self._with_auth_retry(
            lambda: self._post_subscription_edit(
                [("ac", "unsubscribe"), ("s", stream_id)]
            )
        )
        # 400 after the existence pre-check means the feed vanished between
        # check and write (race) — the honest answer is "not found".
        self._require_ok(response, on_bad_request=SubscriptionNotFound(
            "FreshRSS has no subscription with this id."
        ))

    async def move_category(self, stream_id: str, category_id: str) -> None:
        """Move one subscription to an existing category."""
        self._validate_stream_id(stream_id)
        self._validate_category_id(category_id)
        await self._require_category(category_id)
        await self._require_subscription(stream_id)
        response = await self._with_auth_retry(
            lambda: self._post_subscription_edit(
                [("ac", "edit"), ("s", stream_id), ("a", category_id)]
            )
        )
        self._require_ok(response, on_bad_request=SubscriptionNotFound(
            "FreshRSS has no subscription with this id."
        ))

    async def move_to_new_category(self, stream_id: str, label: str) -> None:
        """Move one subscription into a NEW category created from ``label``.

        This is the only FreshRSS control path that creates categories:
        subscription/edit auto-creates the ``a=`` category when missing
        (0013 Gate 1, verified live). Lumi stays explicit about it — the
        label is validated and checked against existing categories first
        (so a typo or a collision never silently creates a stray category,
        and renaming into the localized default name cannot mint a
        duplicate-looking real category), and the move is post-checked
        because upstream "OK" answers are unchecked SQL.
        """
        self._validate_stream_id(stream_id)
        clean = self._validated_label(label)

        categories = await self.list_categories()
        if clean == _RESERVED_CATEGORY_LABEL or any(
            category.label == clean for category in categories
        ):
            raise CategoryLabelConflict("Another category already uses this label.")

        await self._require_subscription(stream_id)
        target = f"{_CATEGORY_PREFIX}{clean}"
        response = await self._with_auth_retry(
            lambda: self._post_subscription_edit(
                [("ac", "edit"), ("s", stream_id), ("a", target)]
            )
        )
        self._require_ok(response, on_bad_request=SubscriptionNotFound(
            "FreshRSS has no subscription with this id."
        ))

        # Post-check: re-read the subscription and require the move to be
        # visible (catches upstream OK-but-nothing-applied answers).
        for subscription in await self.list_subscriptions():
            if subscription.stream_id == stream_id:
                if subscription.category_id != target:
                    raise UpstreamError(
                        "FreshRSS reported success but the move was not applied."
                    )
                return
        raise SubscriptionNotFound("FreshRSS has no subscription with this id.")

    async def export_opml(self) -> bytes:
        """FreshRSS's own OPML export (subscriptions + categories only).

        Proxies GET reader/api/0/subscription/export (verified against
        FreshRSS 1.29.1: 200 + OPML 2.0, categories as nested outlines).
        The body is size-checked and shape-checked (must start with an
        <opml> document) so a broken upstream can never stream garbage to
        the browser. Contains no credentials and no entry content.
        """
        response = await self._with_auth_retry(
            lambda: self._session._authorized_get_raw(
                "reader/api/0/subscription/export"
            )
        )
        if response.status_code != 200:
            raise UpstreamError(
                "FreshRSS subscription/export returned HTTP "
                f"{response.status_code}."
            )
        content = response.content
        if len(content) > _MAX_OPML_EXPORT_BYTES:
            raise UpstreamError("FreshRSS OPML export is unexpectedly large.")
        if b"<opml" not in content[:2048]:
            raise UpstreamError(
                "FreshRSS OPML export has an unexpected shape (no <opml>)."
            )
        return content

    async def export_opml(self) -> bytes:
        """FreshRSS's own OPML export (subscriptions + categories only).

        Proxies GET reader/api/0/subscription/export (verified against
        FreshRSS 1.29.1: 200 + OPML 2.0, categories as nested outlines).
        The body is size-checked and shape-checked (must be an <opml>
        document) so a broken upstream can never stream garbage to the
        browser. Contains no credentials and no entry content.
        """
        response = await self._with_auth_retry(
            lambda: self._session._authorized_get_raw(
                "reader/api/0/subscription/export"
            )
        )
        if response.status_code != 200:
            raise UpstreamError(
                "FreshRSS subscription/export returned HTTP "
                f"{response.status_code}."
            )
        content = response.content
        if len(content) > _MAX_OPML_EXPORT_BYTES:
            raise UpstreamError("FreshRSS OPML export is unexpectedly large.")
        if b"<opml" not in content[:2048]:
            raise UpstreamError(
                "FreshRSS OPML export has an unexpected shape (no <opml>)."
            )
        return content

    async def rename_category(self, category_id: str, new_label: str) -> None:
        """Rename one category; server-confirmed via a post-check read.

        Default-category and silent-no-op traps (see module docstring) are
        guarded: a no-op probe rename (s == dest) detects the default
        category (its API-visible name never matches its DB name), and the
        post-check read detects upstream "OK" answers that changed nothing.
        """
        self._validate_category_id(category_id)
        label = self._validated_label(new_label)

        categories = await self.list_categories()
        if not any(category.id == category_id for category in categories):
            raise CategoryNotFound("FreshRSS has no category with this id.")
        if label == _RESERVED_CATEGORY_LABEL or any(
            category.label == label for category in categories
        ):
            raise CategoryLabelConflict("Another category already uses this label.")

        # No-op probe: renames the category to its own name. A user category
        # has DB name == visible name → 200 OK; the default category's
        # visible name is the localized string, never its DB name → 400.
        probe = await self._with_auth_retry(
            lambda: self._post_rename_tag(category_id, category_id)
        )
        if probe.status_code == 400:
            raise DefaultCategoryImmutable(
                "The FreshRSS default category cannot be renamed."
            )
        self._require_ok(probe, on_bad_request=UpstreamError(
            "FreshRSS refused the category rename probe."
        ))

        response = await self._with_auth_retry(
            lambda: self._post_rename_tag(category_id, f"{_CATEGORY_PREFIX}{label}")
        )
        self._require_ok(response, on_bad_request=UpstreamError(
            "FreshRSS refused the category rename."
        ))

        # Post-check: rename-tag can answer "OK" while applying nothing
        # (UNIQUE(name) or a same-named tag blocks the SQL UPDATE).
        after = await self.list_categories()
        if not any(category.id == f"{_CATEGORY_PREFIX}{label}" for category in after):
            raise UpstreamError(
                "FreshRSS reported success but the rename was not applied."
            )

    # --- internals -------------------------------------------------------

    async def _with_auth_retry(self, operation):
        """Run a control operation; on 401 re-login once and retry once.

        Safe for mutations: FreshRSS checks auth before any mutation logic,
        so a 401 means the request was NOT applied. Timeouts/connection
        errors are never retried (re-read + reconcile is the caller's job).
        """
        try:
            return await operation()
        except AuthenticationError:
            self._session._clear_tokens()
            return await operation()

    async def _post_subscription_edit(
        self, fields: list[tuple[str, str]]
    ) -> httpx.Response:
        auth_token = await self._session._get_auth_token()
        action_token = await self._session._get_action_token(auth_token)
        # 1.29.1 ignores T on subscription/edit; sent anyway per protocol.
        return await self._session._authorized_post_form(
            "reader/api/0/subscription/edit", [("T", action_token), *fields]
        )

    async def _post_rename_tag(self, source: str, dest: str) -> httpx.Response:
        auth_token = await self._session._get_auth_token()
        action_token = await self._session._get_action_token(auth_token)
        return await self._session._authorized_post_form(
            "reader/api/0/rename-tag",
            [("T", action_token), ("s", source), ("dest", dest)],
        )

    def _require_ok(self, response: httpx.Response, *, on_bad_request) -> None:
        """Interpret a mutation response: 200+"OK", mapped 400, else error."""
        if response.status_code == 400:
            raise on_bad_request
        if response.status_code != 200:
            raise UpstreamError(
                f"FreshRSS mutation returned HTTP {response.status_code}."
            )
        if response.text.strip() != "OK":
            raise UpstreamError("FreshRSS mutation returned an unexpected body.")

    async def _require_category(self, category_id: str) -> None:
        for category in await self.list_categories():
            if category.id == category_id:
                return
        raise CategoryNotFound("FreshRSS has no category with this id.")

    async def _require_subscription(self, stream_id: str) -> None:
        for subscription in await self.list_subscriptions():
            if subscription.stream_id == stream_id:
                return
        raise SubscriptionNotFound("FreshRSS has no subscription with this id.")

    @staticmethod
    def _iter_list(payload: dict, source: str, key: str):
        items = payload.get(key)
        if not isinstance(items, list):
            raise UpstreamError(f"FreshRSS {source} '{key}' is not a list.")
        for item in items:
            if not isinstance(item, dict):
                raise UpstreamError(f"FreshRSS {source} item is not an object.")
            yield item

    @staticmethod
    def _category_of(item: dict) -> tuple[str | None, str | None]:
        """categories[0] = FreshRSS 单分类（greader 模型）；形状异常 → 无分类。"""
        categories = item.get("categories")
        if not isinstance(categories, list) or not categories:
            return None, None
        first = categories[0]
        if not isinstance(first, dict):
            return None, None
        raw_id = first.get("id")
        raw_label = first.get("label")
        category_id = raw_id if isinstance(raw_id, str) and raw_id else None
        category_label = raw_label if isinstance(raw_label, str) and raw_label else None
        return category_id, category_label

    @staticmethod
    def _validate_feed_url(feed_url: str) -> None:
        if len(feed_url) > _MAX_FEED_URL_LENGTH:
            raise InvalidFeedUrl("Feed URL is too long.")
        parts = urllib.parse.urlsplit(feed_url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise InvalidFeedUrl("Feed URL must be an absolute http(s) URL.")

    @staticmethod
    def _validated_label(label: str) -> str:
        """Shared label rules (rename + create-on-move): strip, 1-128, no '/'."""
        clean = label.strip()
        if not clean or "/" in clean or len(clean) > _MAX_LABEL_LENGTH:
            raise InvalidCategoryLabel(
                "Category label must be 1-128 characters and contain no '/'."
            )
        return clean

    @staticmethod
    def _validate_stream_id(stream_id: str) -> None:
        """Only stream ids we could have produced (feed/<positive int>)."""
        body = stream_id.removeprefix("feed/")
        if (
            not stream_id.startswith("feed/")
            or not body.isdigit()
            or body.startswith("0")
            or len(body) > 10
        ):
            raise InvalidSubscriptionReference(
                "Stream id is not a well-formed feed id."
            )

    @staticmethod
    def _validate_category_id(category_id: str) -> None:
        label = category_id.removeprefix(_CATEGORY_PREFIX)
        if not category_id.startswith(_CATEGORY_PREFIX) or not label:
            raise InvalidCategoryReference(
                "categoryId must be a user/-/label/<名> reference."
            )
