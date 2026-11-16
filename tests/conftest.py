import asyncio

import httpx
import pytest

from app.config import Settings


@pytest.fixture
def make_settings(monkeypatch):
    """Build Settings from explicit values only, ignoring the real environment and .env."""

    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)

    def factory(**overrides) -> Settings:
        values = {
            "log_file": None,
            "runs_dir": None,
            "max_retries": 0,
            "verify_public_access": False,
            "request_timeout": 5,
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return factory


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as http_client:
        yield http_client


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch):
    """Retries back off with asyncio.sleep; skip the wait in tests."""
    real_sleep = asyncio.sleep

    async def instant(delay, *args, **kwargs):
        await real_sleep(0)

    monkeypatch.setattr("app.platforms.base.asyncio.sleep", instant)
