"""Registry of supported platforms. Add a new integration by appending its class here."""

from typing import Dict, List, Type

from app.platforms.base import BasePlatform, PlatformError, Post, PublishedPost
from app.platforms.bluesky import BlueskyPlatform
from app.platforms.devto import DevToPlatform
from app.platforms.github_gist import GitHubGistPlatform
from app.platforms.huggingface import HuggingFacePlatform
from app.platforms.telegram import TelegramPlatform
from app.platforms.telegraph import TelegraphPlatform
from app.platforms.writeas import WriteAsPlatform

PLATFORM_CLASSES: List[Type[BasePlatform]] = [
    BlueskyPlatform,
    DevToPlatform,
    GitHubGistPlatform,
    HuggingFacePlatform,
    TelegramPlatform,
    TelegraphPlatform,
    WriteAsPlatform,
]

PLATFORMS_BY_KEY: Dict[str, Type[BasePlatform]] = {cls.key: cls for cls in PLATFORM_CLASSES}

__all__ = [
    "BasePlatform",
    "PLATFORM_CLASSES",
    "PLATFORMS_BY_KEY",
    "PlatformError",
    "Post",
    "PublishedPost",
]
