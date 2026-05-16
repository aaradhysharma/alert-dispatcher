"""Environment-backed settings (no secrets in source control)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Values loaded from the process environment and optional `.env` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mock_email_api_key: str
    mock_slack_webhook: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
