"""FreshRSS connection settings for the LumiRSS BFF."""

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
