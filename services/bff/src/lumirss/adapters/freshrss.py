"""FreshRSSAdapter — translates the FreshRSS Google Reader API into the
minimal LumiRSS feed model.

All FreshRSS-specific knowledge lives here: ClientLogin, the
``Authorization: GoogleLogin auth=...`` header, and the raw subscription
JSON shape. Routes never see any of it.
"""

import httpx

from lumirss.config import FreshRSSSettings


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

    async def list_feeds(self) -> list[Feed]:
        """Return the LumiRSS feed list, logging in first if needed."""
        token = await self._get_auth_token()
        try:
            response = await self._request_subscription_list(token)
        except AuthenticationError:
            # Token invalidated (e.g. API password changed): re-login once
            # and retry once. No retry framework, no loop.
            self._auth_token = None
            token = await self._get_auth_token()
            response = await self._request_subscription_list(token)
        return self._parse_subscriptions(response)

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
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
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
        return token

    async def _request_subscription_list(self, token: str) -> dict:
        try:
            response = await self._client.get(
                f"{self._base_url}/api/greader.php/reader/api/0/subscription/list",
                params={"output": "json"},
                headers={"Authorization": f"GoogleLogin auth={token}"},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
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
