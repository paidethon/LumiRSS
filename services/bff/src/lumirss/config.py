"""FreshRSS connection settings for the LumiRSS BFF."""

import urllib.parse

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
