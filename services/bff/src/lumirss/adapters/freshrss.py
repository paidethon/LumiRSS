"""FreshRSSAdapter — translates the FreshRSS Google Reader API into the
minimal LumiRSS models.

All FreshRSS-specific knowledge lives here: ClientLogin, the
``Authorization: GoogleLogin auth=...`` header, the reading-list /
item-contents endpoints, the raw entry JSON shape, and the HTML-to-text
extraction for contentText. Routes never see any of it.
"""

import urllib.parse
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Literal

import httpx

from lumirss.config import FreshRSSSettings
from lumirss.entryref import encode_entry_ref
from lumirss.models import EntryDetail, EntryListItem, EntryPage

EntryView = Literal["all", "unread", "starred"]


class AdapterError(Exception):
    """Base class for all errors raised by the FreshRSSAdapter."""


class ConfigError(AdapterError):
    """FreshRSS settings are missing or invalid."""


class AuthenticationError(AdapterError):
    """FreshRSS rejected our credentials (ClientLogin returned 401)."""


class UpstreamConnectionError(AdapterError):
    """FreshRSS is unreachable (connection failure or timeout)."""


class UpstreamError(AdapterError):
    """FreshRSS returned an unexpected status or unparseable body."""


_NETWORK_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)

# reading-list semantics (FreshRSS 1.29.1 source, confirmed by live probe):
# all entries except hidden ones; STATE_ALL when no it/xt filter (read +
# unread); n = max items; r defaults to "d" (newest first). View filters are
# passed upstream as the `it` parameter so FreshRSS does the filtering.
_ENTRY_LIST_LIMIT = 20

# FreshRSS state markers (1.29.1 source verified; probe confirmed).
_READ_MARKER = "user/-/state/com.google/read"
_STARRED_MARKER = "user/-/state/com.google/starred"
_UNREAD_FILTER = "user/-/state/com.google/unread"
_STARRED_FILTER = "user/-/state/com.google/starred"

# view → upstream `it` filter (all = no filter).
_VIEW_FILTERS = {"unread": _UNREAD_FILTER, "starred": _STARRED_FILTER}

# Block-level tags that produce a line break in contentText.
_BLOCK_TAGS = frozenset(
    "p div br li ul ol h1 h2 h3 h4 h5 h6 blockquote pre tr table section "
    "article aside header footer nav figure hr dl dt dd form fieldset".split()
)


class _TextExtractor(HTMLParser):
    """Deterministic HTML-to-text extraction (text-only normalization).

    This is NOT an HTML sanitizer: the goal is that no markup and no
    script/style content survives into the plain-text output.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skipping_depth = 0  # inside <script>/<style>

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ARG002
        if self._skipping_depth:
            return
        if tag in ("script", "style"):
            self._skipping_depth = 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._skipping_depth:
            if tag in ("script", "style"):
                self._skipping_depth = 0
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:  # noqa: ARG002
        if not self._skipping_depth and tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping_depth:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts).strip()


def html_to_text(html: str) -> str:
    """Convert untrusted entry HTML into plain text (tags/entities/blocks).

    Standard library only: tags removed, entities decoded, block tags
    become line breaks, script/style content dropped entirely.
    """
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
        extractor.close()
    except Exception as exc:  # malformed HTML must not 500 the whole page
        raise UpstreamError("Entry content could not be converted to text.") from exc
    return extractor.text()


class EntryNotFound(AdapterError):
    """The entry id is well-formed but FreshRSS has no such entry."""


class Feed:
    """Minimal LumiRSS feed model (0002 scope: title + feedUrl only)."""

    def __init__(self, title: str, feed_url: str) -> None:
        self.title = title
        self.feed_url = feed_url

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Feed)
            and self.title == other.title
            and self.feed_url == other.feed_url
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"Feed(title={self.title!r}, feed_url={self.feed_url!r})"


class FreshRSSAdapter:
    """App-scoped adapter holding the auth token in process memory only."""

    def __init__(self, client: httpx.AsyncClient, settings: FreshRSSSettings) -> None:
        self._client = client
        self._base_url = settings.FRESHRSS_BASE_URL.rstrip("/")
        self._username = settings.FRESHRSS_USERNAME
        self._api_password = settings.FRESHRSS_API_PASSWORD
        self._auth_token: str | None = None
        self._action_token: str | None = None

    async def list_feeds(self) -> list[Feed]:
        """Return the LumiRSS feed list, logging in first if needed."""
        token = await self._get_auth_token()
        try:
            response = await self._request_subscription_list(token)
        except AuthenticationError:
            # Token invalidated (e.g. API password changed): re-login once
            # and retry once. No retry framework, no loop.
            self._clear_tokens()
            token = await self._get_auth_token()
            response = await self._request_subscription_list(token)
        return self._parse_subscriptions(response)

    async def list_entries(
        self,
        *,
        view: EntryView = "all",
        feed_url: str | None = None,
        continuation: str | None = None,
    ) -> EntryPage:
        """Return one filtered page of entries, never their bodies.

        Filtering happens upstream: ``view`` becomes FreshRSS's ``it``
        parameter and ``feed_url`` selects the feed's own stream, so the
        returned page is already filtered (no post-filtering here). The
        upstream continuation is returned as-is; public cursor semantics
        belong to the route layer.
        """
        token = await self._get_auth_token()
        try:
            payload = await self._request_stream(token, view, feed_url, continuation)
        except AuthenticationError:
            self._clear_tokens()
            token = await self._get_auth_token()
            payload = await self._request_stream(token, view, feed_url, continuation)
        items: list[EntryListItem] = []
        for item in self._iter_items(payload, "stream/contents"):
            base = self._common_fields(item)
            if base is None:  # no id → cannot be referenced, skip the item
                continue
            items.append(
                EntryListItem(
                    entryRef=encode_entry_ref(base["item_id"]),
                    title=base["title"],
                    feedTitle=base["feed_title"],
                    author=base["author"],
                    url=base["url"],
                    publishedAt=base["published_at"],
                    read=base["read"],
                    starred=base["starred"],
                )
            )
        return EntryPage(
            items=items,
            upstreamContinuation=self._continuation_of(payload),
        )

    async def get_entry(self, item_id: str) -> EntryDetail:
        """Return one entry with its body as plain text (read-only).

        FreshRSS answers a missing item with HTTP 200 + empty items (not
        404), and this method always sends exactly one ``i``.
        """
        token = await self._get_auth_token()
        try:
            payload = await self._request_item_contents(token, item_id)
        except AuthenticationError:
            self._clear_tokens()
            token = await self._get_auth_token()
            payload = await self._request_item_contents(token, item_id)
        items = list(self._iter_items(payload, "items/contents"))
        if not items:
            raise EntryNotFound("FreshRSS has no entry with this id.")
        if len(items) > 1:  # defensive: we asked for exactly one
            raise UpstreamError(
                "FreshRSS items/contents returned more than one item."
            )
        base = self._common_fields(items[0])
        if base is None:
            raise UpstreamError("FreshRSS items/contents item is missing its id.")
        return EntryDetail(
            entryRef=encode_entry_ref(base["item_id"]),
            title=base["title"],
            feedTitle=base["feed_title"],
            author=base["author"],
            url=base["url"],
            publishedAt=base["published_at"],
            read=base["read"],
            starred=base["starred"],
            contentText=html_to_text(base["content_html"]),
        )

    async def _get_auth_token(self) -> str:
        if self._auth_token is not None:
            return self._auth_token
        try:
            response = await self._client.post(
                f"{self._base_url}/api/greader.php/accounts/ClientLogin",
                data={
                    "Email": self._username,
                    "Passwd": self._api_password.get_secret_value(),
                },
            )
        except _NETWORK_ERRORS as exc:
            raise UpstreamConnectionError(
                "Could not reach FreshRSS. Is the FreshRSS container running?"
            ) from exc
        if response.status_code == 401:
            raise AuthenticationError(
                "FreshRSS rejected the credentials. Check FRESHRSS_API_PASSWORD."
            )
        if response.status_code != 200:
            raise UpstreamError(
                f"FreshRSS ClientLogin returned HTTP {response.status_code}."
            )
        token = self._extract_auth_token(response.text)
        if token is None:
            raise UpstreamError("FreshRSS ClientLogin response missing Auth token.")
        self._auth_token = token
        # A fresh login invalidates any cached action token with it.
        self._action_token = None
        return token

    async def set_entry_state(
        self,
        item_id: str,
        *,
        read: bool | None = None,
        starred: bool | None = None,
    ) -> None:
        """Set (never toggle) the read/starred state of one entry.

        Set semantics keep writes idempotent: read=True twice stays read.
        Both fields, when given, are sent in a single edit-tag request.
        """
        if read is None and starred is None:
            raise ValueError("At least one of read/starred must be provided.")
        auth_token = await self._get_auth_token()
        try:
            action_token = await self._get_action_token(auth_token)
            response = await self._request_edit_tag(
                auth_token, action_token, item_id, read=read, starred=starred
            )
        except AuthenticationError:
            # Auth or action token rejected: clear both, re-login, get a new
            # action token, and retry the write exactly once. No loop.
            self._clear_tokens()
            auth_token = await self._get_auth_token()
            action_token = await self._get_action_token(auth_token)
            response = await self._request_edit_tag(
                auth_token, action_token, item_id, read=read, starred=starred
            )

    async def _get_action_token(self, auth_token: str) -> str:
        """Fetch and cache the write action token (GET /token, memory only)."""
        if self._action_token is not None:
            return self._action_token
        try:
            response = await self._get_action_token_request(auth_token)
        except AuthenticationError:
            # Stale auth token: clear both tokens, re-login once, retry once.
            self._clear_tokens()
            auth_token = await self._get_auth_token()
            response = await self._get_action_token_request(auth_token)
        self._action_token = self._validate_action_token(response)
        return self._action_token

    async def _get_action_token_request(self, auth_token: str) -> httpx.Response:
        try:
            return await self._client.get(
                f"{self._base_url}/api/greader.php/reader/api/0/token",
                headers={"Authorization": f"GoogleLogin auth={auth_token}"},
            )
        except _NETWORK_ERRORS as exc:
            raise UpstreamConnectionError(
                "Could not reach FreshRSS. Is the FreshRSS container running?"
            ) from exc

    @staticmethod
    def _validate_action_token(response: httpx.Response) -> str:
        """Reject values that FreshRSS only accepts as legacy compatibility."""
        if response.status_code == 401:
            raise AuthenticationError("FreshRSS session token rejected.")
        if response.status_code != 200:
            raise UpstreamError(
                f"FreshRSS token endpoint returned HTTP {response.status_code}."
            )
        token = response.text.strip()
        if not token or token == "x":
            raise UpstreamError("FreshRSS returned an unusable action token.")
        return token

    async def _request_edit_tag(
        self,
        auth_token: str,
        action_token: str,
        item_id: str,
        *,
        read: bool | None,
        starred: bool | None,
    ) -> httpx.Response:
        # Both states go into ONE edit-tag request. Repeated form fields need
        # a list of pairs urlencoded manually: httpx 0.28 AsyncClient treats a
        # list-of-tuples `data` as a sync stream (RuntimeError).
        fields: list[tuple[str, str]] = [
            ("T", action_token),
            ("i", item_id),
        ]
        if read is not None:
            fields.append(("a" if read else "r", _READ_MARKER))
        if starred is not None:
            fields.append(("a" if starred else "r", _STARRED_MARKER))
        try:
            response = await self._client.post(
                f"{self._base_url}/api/greader.php/reader/api/0/edit-tag",
                content=urllib.parse.urlencode(fields),
                headers={
                    "Authorization": f"GoogleLogin auth={auth_token}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
        except _NETWORK_ERRORS as exc:
            raise UpstreamConnectionError(
                "Could not reach FreshRSS. Is the FreshRSS container running?"
            ) from exc
        if response.status_code == 401:
            raise AuthenticationError("FreshRSS session token rejected.")
        if response.status_code != 200:
            raise UpstreamError(
                f"FreshRSS edit-tag returned HTTP {response.status_code}."
            )
        if response.text.strip() != "OK":
            raise UpstreamError("FreshRSS edit-tag returned an unexpected body.")
        return response

    async def _request_subscription_list(self, token: str) -> dict:
        try:
            response = await self._client.get(
                f"{self._base_url}/api/greader.php/reader/api/0/subscription/list",
                params={"output": "json"},
                headers={"Authorization": f"GoogleLogin auth={token}"},
            )
        except _NETWORK_ERRORS as exc:
            raise UpstreamConnectionError(
                "Could not reach FreshRSS. Is the FreshRSS container running?"
            ) from exc
        if response.status_code == 401:
            raise AuthenticationError("FreshRSS session token rejected.")
        if response.status_code != 200:
            raise UpstreamError(
                f"FreshRSS subscription/list returned HTTP {response.status_code}."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError("FreshRSS subscription/list returned invalid JSON.") from exc
        if not isinstance(payload, dict) or "subscriptions" not in payload:
            raise UpstreamError("FreshRSS subscription/list JSON has unexpected shape.")
        return payload

    async def _request_stream(
        self,
        token: str,
        view: EntryView,
        feed_url: str | None,
        continuation: str | None,
    ) -> dict:
        """GET stream/contents (read-only, bounded n=20, filtered upstream)."""
        if feed_url is None:
            stream_path = "reading-list"
        else:
            # The feed URL is percent-encoded into the stream path (verified
            # against 1.29.1: the server regex allows '%' and urldecodes).
            stream_path = f"feed/{urllib.parse.quote(feed_url, safe='')}"
        params: dict[str, str] = {"output": "json", "n": str(_ENTRY_LIST_LIMIT)}
        it_filter = _VIEW_FILTERS.get(view)
        if it_filter is not None:
            params["it"] = it_filter
        if continuation is not None:
            params["c"] = continuation
        try:
            response = await self._client.get(
                f"{self._base_url}/api/greader.php/reader/api/0/stream/contents/{stream_path}",
                params=params,
                headers={"Authorization": f"GoogleLogin auth={token}"},
            )
        except _NETWORK_ERRORS as exc:
            raise UpstreamConnectionError(
                "Could not reach FreshRSS. Is the FreshRSS container running?"
            ) from exc
        if response.status_code == 401:
            raise AuthenticationError("FreshRSS session token rejected.")
        if response.status_code != 200:
            raise UpstreamError(
                f"FreshRSS stream/contents returned HTTP {response.status_code}."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError("FreshRSS stream/contents returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise UpstreamError("FreshRSS stream/contents JSON has unexpected shape.")
        return payload

    async def _request_item_contents(self, token: str, item_id: str) -> dict:
        """POST stream/items/contents with exactly one ``i`` (read-only)."""
        try:
            response = await self._client.post(
                f"{self._base_url}/api/greader.php/reader/api/0/stream/items/contents",
                data={"i": item_id},
                headers={"Authorization": f"GoogleLogin auth={token}"},
            )
        except _NETWORK_ERRORS as exc:
            raise UpstreamConnectionError(
                "Could not reach FreshRSS. Is the FreshRSS container running?"
            ) from exc
        if response.status_code == 401:
            raise AuthenticationError("FreshRSS session token rejected.")
        if response.status_code != 200:
            raise UpstreamError(
                f"FreshRSS items/contents returned HTTP {response.status_code}."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError("FreshRSS items/contents returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise UpstreamError("FreshRSS items/contents JSON has unexpected shape.")
        return payload

    def _clear_tokens(self) -> None:
        """Invalidate both tokens together (they share credential lifetime)."""
        self._auth_token = None
        self._action_token = None

    @staticmethod
    def _continuation_of(payload: dict) -> str | None:
        continuation = payload.get("continuation")
        if isinstance(continuation, str) and continuation:
            return continuation
        return None

    @staticmethod
    def _iter_items(payload: dict, source: str):
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise UpstreamError(f"FreshRSS {source} 'items' is not a list.")
        for item in items:
            if not isinstance(item, dict):
                raise UpstreamError(f"FreshRSS {source} item is not an object.")
            yield item

    @staticmethod
    def _common_fields(item: dict) -> dict | None:
        """Normalize the fields shared by list and detail items.

        Returns None when the item has no usable id (it cannot be
        referenced at all); every other missing field is tolerated.
        """
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            return None
        title = item.get("title")
        title = title if isinstance(title, str) else ""
        origin = item.get("origin")
        feed_title = (
            origin.get("title")
            if isinstance(origin, dict) and isinstance(origin.get("title"), str)
            else ""
        )
        author = item.get("author")
        author = author if isinstance(author, str) and author else None
        alternate = item.get("alternate")
        url = None
        if isinstance(alternate, list) and alternate:
            first = alternate[0]
            if isinstance(first, dict) and isinstance(first.get("href"), str):
                url = first["href"]
        published = item.get("published")
        published_at = None
        if isinstance(published, int) and not isinstance(published, bool) and published >= 0:
            published_at = (
                datetime.fromtimestamp(published, tz=timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ")
            )
        categories = item.get("categories")
        categories = categories if isinstance(categories, list) else []
        return {
            "item_id": item_id,
            "title": title,
            "feed_title": feed_title,
            "author": author,
            "url": url,
            "published_at": published_at,
            "read": _READ_MARKER in categories,
            "starred": _STARRED_MARKER in categories,
            "content_html": FreshRSSAdapter._content_html_of(item),
        }

    @staticmethod
    def _content_html_of(item: dict) -> str:
        summary = item.get("summary")
        if isinstance(summary, dict) and isinstance(summary.get("content"), str):
            return summary["content"]
        return ""

    @staticmethod
    def _extract_auth_token(body: str) -> str | None:
        for line in body.splitlines():
            if line.startswith("Auth="):
                return line[len("Auth="):].strip()
        return None

    @staticmethod
    def _parse_subscriptions(payload: dict) -> list[Feed]:
        feeds: list[Feed] = []
        for item in payload.get("subscriptions", []):
            title = item.get("title")
            url = item.get("url")
            if not isinstance(title, str) or not isinstance(url, str):
                raise UpstreamError(
                    "FreshRSS subscription entry missing 'title' or 'url'."
                )
            feeds.append(Feed(title=title, feed_url=url))
        return feeds
