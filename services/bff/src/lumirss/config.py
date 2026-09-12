"""Connection and storage settings for the LumiRSS BFF."""

import urllib.parse
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Default Lumi data directory: <services/bff>/data (git-ignored).
_DEFAULT_LUMI_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class FreshRSSSettings(BaseSettings):
    """Settings read from environment variables / .env.

    Validated lazily (on first /api/v1/feeds request), never at process
    startup, so /health/live stays available even without configuration.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    FRESHRSS_BASE_URL: str = ""
    FRESHRSS_USERNAME: str = ""
    FRESHRSS_API_PASSWORD: SecretStr = SecretStr("")
    # 0013 Gate 4: optional browser-safe public URL of the FreshRSS web
    # UI (advanced escape hatch). Blank = not exposed. Deliberately
    # never derived from FRESHRSS_BASE_URL, which may be a Docker-internal
    # hostname the user's browser cannot (and must not) reach.
    FRESHRSS_PUBLIC_URL: str = ""

    @field_validator("FRESHRSS_BASE_URL", "FRESHRSS_USERNAME")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("FRESHRSS_API_PASSWORD")
    @classmethod
    def must_not_be_blank_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("FRESHRSS_PUBLIC_URL")
    @classmethod
    def must_be_safe_public_url(cls, value: str) -> str:
        """Optional, but when set: absolute http(s), no credentials/query/fragment."""
        clean = value.strip()
        if not clean:
            return ""
        parts = urllib.parse.urlsplit(clean)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("must be an absolute http(s) URL")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("must not carry credentials, a query or a fragment")
        return clean.rstrip("/")


def _validate_service_base_url(value: str, name: str) -> str:
    """Operator-configured service base URL (0014 RSSHub).

    Structural validation only — unlike FRESHRSS_PUBLIC_URL, the host MAY
    be internal (loopback / Docker network): this is infrastructure the
    operator deliberately wired, never user input, and it never reaches
    the browser as a base for fetching.
    """
    clean = value.strip()
    if not clean:
        return ""
    parts = urllib.parse.urlsplit(clean)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"{name} must be an absolute http(s) URL")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError(f"{name} must not carry credentials, a query or a fragment")
    if parts.path not in ("", "/"):
        raise ValueError(f"{name} must not carry a path (host root only)")
    return clean.rstrip("/")


class RssHubSettings(BaseSettings):
    """RSSHub connection settings for the 0014 source discovery flow.

    Read lazily per request like FreshRSSSettings. Both values are
    operator-configured server-side; the browser never learns them
    directly (it only ever sees constructed feed URLs the user asked to
    subscribe to).

    - RSSHUB_BASE_URL: base the BFF itself fetches for preview.
    - RSSHUB_FRESHRSS_BASE_URL: optional base as reachable from the
      FreshRSS container (e.g. http://rsshub:1200 vs 127.0.0.1:1200 on
      the host — 0008 verified the dual view). Defaults to
      RSSHUB_BASE_URL. This base is what subscription feedUrls are built
      from, because FreshRSS (not the BFF) fetches feeds after subscribe.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    RSSHUB_BASE_URL: str = ""
    RSSHUB_FRESHRSS_BASE_URL: str = ""

    @field_validator("RSSHUB_BASE_URL")
    @classmethod
    def must_be_valid_base(cls, value: str) -> str:
        return _validate_service_base_url(value, "RSSHUB_BASE_URL")

    @field_validator("RSSHUB_FRESHRSS_BASE_URL")
    @classmethod
    def must_be_valid_freshrss_base(cls, value: str) -> str:
        return _validate_service_base_url(value, "RSSHUB_FRESHRSS_BASE_URL")

    @property
    def freshrss_base_url(self) -> str:
        """The base FreshRSS will actually fetch (fallback to BASE_URL)."""
        return self.RSSHUB_FRESHRSS_BASE_URL or self.RSSHUB_BASE_URL


class LumiSettings(BaseSettings):
    """Lumi-owned state + AI settings (0015, extended 0018).

    - LUMIRSS_DB_PATH: the Lumi SQLite file. Defaults to
      <services/bff>/data/lumi.sqlite (git-ignored); tests override it
      with a temp path. The file is created on first storage use.
    - LUMIRSS_DATA_DIR: base directory for Lumi-owned runtime state
      (secrets.json, local backups, restore staging). Defaults to the
      LUMIRSS_DB_PATH parent.
    - FRESHRSS_DATA_DIR: where the FreshRSS data directory is mounted
      READ-ONLY for consistent online backup (0018). Blank = FreshRSS
      data backup unavailable (dev mode).
    - AI_API_KEY: the OpenAI-compatible API key. Server-side secret only:
      it never leaves the BFF, is never logged, and the browser only ever
      learns ``configured: true/false``. Blank = AI not configured.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    LUMIRSS_DB_PATH: str = str(_DEFAULT_LUMI_DATA_DIR / "lumi.sqlite")
    LUMIRSS_DATA_DIR: str = ""
    FRESHRSS_DATA_DIR: str = ""
    LUMIRSS_VERSION: str = "0.1.0"
    LUMIRSS_COMMIT: str = ""
    # phase2 M3: base URL FreshRSS uses to reach this BFF's Atom endpoints
    # (docker-internal address, e.g. http://lumirss-bff:8000).
    LUMIRSS_ATOM_BASE_URL: str = ""
    AI_API_KEY: SecretStr = SecretStr("")
    LUMIRSS_INTERNAL_TOKEN: SecretStr = SecretStr("")
    # Search projection sync cadence (0022); 0 disables the background sync
    # (tests set this to stay hermetic from the developer's FreshRSS).
    LUMIRSS_SEARCH_SYNC_INTERVAL: float = 60.0
    # --- Persistent single-user session auth ---
    # "basic" (default) keeps the historical proxy-level Basic Auth contract;
    # "session" activates BFF-side login: bcrypt password check, long-lived
    # random session cookies, sliding renewal (see auth_store.py).
    LUMIRSS_AUTH_MODE: Literal["basic", "session"] = "basic"
    # Absolute inactivity window for a session; regular use slides it forward
    # so an actively-used device effectively never re-prompts.
    LUMIRSS_SESSION_MAX_AGE_DAYS: int = 180
    # Secure cookies (__Host- prefix + Secure attribute) whenever the site is
    # served over HTTPS (every production deployment). Plain-HTTP dev (vite
    # proxy on localhost) opts out via .env / docker-compose.yml.
    LUMIRSS_SESSION_SECURE_COOKIES: bool = True
    # Optional exact public origin ("https://rss.example.com") used by the
    # CSRF Origin check behind reverse proxies; blank = compare against the
    # forwarded Host header (both Caddys preserve it in this stack).
    LUMIRSS_PUBLIC_ORIGIN: str = ""

    @field_validator("LUMIRSS_SESSION_MAX_AGE_DAYS")
    @classmethod
    def _sane_session_age(cls, value: int) -> int:
        if not 1 <= value <= 3650:
            raise ValueError("must be between 1 and 3650 days")
        return value

    @field_validator("LUMIRSS_SEARCH_SYNC_INTERVAL")
    @classmethod
    def _sane_search_interval(cls, value: float) -> float:
        if value < 0:
            raise ValueError("must be 0 (disabled) or a positive number of seconds")
        return value

    @property
    def ai_configured(self) -> bool:
        return bool(self.AI_API_KEY.get_secret_value().strip())

    @property
    def data_dir(self) -> Path:
        """Base directory for Lumi-owned runtime state (0018)."""
        if self.LUMIRSS_DATA_DIR.strip():
            return Path(self.LUMIRSS_DATA_DIR).expanduser()
        return Path(self.LUMIRSS_DB_PATH).expanduser().parent

    @property
    def secrets_path(self) -> Path:
        """Server-side secret store file (chmod 600, never in SQLite)."""
        return self.data_dir / "secrets.json"

    @property
    def local_backups_dir(self) -> Path:
        """Where full backups are written for the 'local' target."""
        return self.data_dir / "backups"

    @property
    def restore_staging_dir(self) -> Path:
        """Staging area for validated restore packages (0018)."""
        return self.data_dir / "restore-staging"
