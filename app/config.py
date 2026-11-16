"""Application settings, loaded from environment variables and an optional .env file."""

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # General
    app_name: str = "Automated Multi-Platform Posting System"
    timezone: str = Field(default="Asia/Kolkata", description="IANA zone used for result timestamps")
    log_level: str = "INFO"
    log_file: Optional[str] = "logs/posting.log"
    runs_dir: Optional[str] = Field(default="logs/runs", description="Folder where each run's JSON result is saved")

    # Outbound HTTP behaviour
    request_timeout: float = Field(default=15.0, gt=0)
    max_retries: int = Field(default=1, ge=0, le=3)
    verify_public_access: bool = True
    enabled_platforms: Optional[str] = Field(
        default=None,
        description="Comma-separated platform keys to use. Empty means every configured platform.",
    )

    # Telegraph (telegra.ph). A token is created on first use when this is empty.
    telegraph_access_token: Optional[SecretStr] = None
    telegraph_author_name: str = "Automated Posting"

    # Write.as. Posts anonymously when no token is set.
    writeas_access_token: Optional[SecretStr] = None

    # GitHub Gist
    github_token: Optional[SecretStr] = None

    # DEV Community (dev.to)
    devto_api_key: Optional[SecretStr] = None
    devto_tags: str = "python,fastapi,automation"

    # Hugging Face Hub
    hf_token: Optional[SecretStr] = None
    hf_repo_id: Optional[str] = Field(
        default=None,
        description="owner/name of the repo that hosts the discussions. Defaults to <user>/automated-posting-feed",
    )
    hf_repo_type: str = "dataset"

    # Bluesky (AT Protocol)
    bluesky_handle: Optional[str] = Field(default=None, description="e.g. yourname.bsky.social")
    bluesky_app_password: Optional[SecretStr] = None
    bluesky_service: str = "https://bsky.social"

    # Telegram Bot API
    telegram_bot_token: Optional[SecretStr] = None
    telegram_chat_id: Optional[str] = Field(default=None, description="@channel_username or numeric chat id")

    @property
    def enabled_platform_keys(self) -> Optional[List[str]]:
        if not self.enabled_platforms:
            return None
        keys = [key.strip().lower() for key in self.enabled_platforms.split(",")]
        return [key for key in keys if key]


@lru_cache
def get_settings() -> Settings:
    return Settings()
