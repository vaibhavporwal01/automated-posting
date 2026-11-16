"""Shared contract and HTTP helpers for every platform integration."""

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Dict, List, Optional, Tuple

import httpx

from app.config import Settings

logger = logging.getLogger("posting.platforms")

USER_AGENT = "automated-posting/1.0 (+https://github.com/vaibhavporwal01/automated-posting)"
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRY_AFTER_SECONDS = 5.0


@dataclass(frozen=True)
class Post:
    """A validated message, plus the pieces some platforms need separately."""

    text: str
    link: str

    @property
    def title(self) -> str:
        """Short headline for platforms that require one (Dev.to, Telegraph, Gist...)."""
        return derive_title(self.text, self.link)


@dataclass(frozen=True)
class PublishedPost:
    url: str
    public: bool  # whether the platform publishes it publicly; verified later by the service


class PlatformError(Exception):
    """A failure the API should report for one platform without affecting the others."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class BasePlatform(ABC):
    """One third-party destination.

    Subclasses declare their name, docs and required settings, and implement
    ``publish``. They should raise ``PlatformError`` with a readable message
    for anything that goes wrong.
    """

    key: ClassVar[str]
    name: ClassVar[str]
    docs_url: ClassVar[str]
    required_settings: ClassVar[Tuple[str, ...]] = ()

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client

    @classmethod
    def missing_settings(cls, settings: Settings) -> List[str]:
        return [name.upper() for name in cls.required_settings if not getattr(settings, name)]

    @classmethod
    def is_configured(cls, settings: Settings) -> bool:
        return not cls.missing_settings(settings)

    @abstractmethod
    async def publish(self, post: Post) -> PublishedPost:
        """Publish the post and return where it lives."""

    # ------------------------------------------------------------------ helpers

    def secret(self, name: str) -> str:
        value = getattr(self.settings, name)
        return value.get_secret_value() if hasattr(value, "get_secret_value") else str(value)

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send a request, retrying timeouts, dropped connections, 429 and 5xx responses.

        The final response is returned even when it is an error so the caller
        can turn the platform's own error body into a message.
        """
        headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
        attempts = self.settings.max_retries + 1

        for attempt in range(1, attempts + 1):
            try:
                response = await self.client.request(method, url, headers=headers, **kwargs)
            except httpx.TimeoutException:
                if attempt < attempts:
                    self._log_retry("timeout", attempt, attempts)
                    await self._backoff(attempt)
                    continue
                raise PlatformError(
                    f"Request timed out after {self.settings.request_timeout:g}s ({attempts} attempt(s))."
                ) from None
            except httpx.TransportError as exc:
                if attempt < attempts:
                    self._log_retry(type(exc).__name__, attempt, attempts)
                    await self._backoff(attempt)
                    continue
                raise PlatformError(
                    f"Could not reach {httpx.URL(url).host}: {type(exc).__name__} ({attempts} attempt(s))."
                ) from None

            if response.status_code in _RETRYABLE_STATUS and attempt < attempts:
                self._log_retry(f"HTTP {response.status_code}", attempt, attempts)
                await self._backoff(attempt, response.headers.get("Retry-After"))
                continue
            return response

        raise PlatformError("Request failed.")  # pragma: no cover - loop always returns or raises

    def _log_retry(self, reason: str, attempt: int, attempts: int) -> None:
        logger.warning("platform=%s retrying after %s (attempt %s/%s)", self.name, reason, attempt, attempts)

    async def _backoff(self, attempt: int, retry_after: Optional[str] = None) -> None:
        delay = 0.5 * (2 ** (attempt - 1))
        if retry_after:
            try:
                delay = min(float(retry_after), _MAX_RETRY_AFTER_SECONDS)
            except ValueError:
                pass
        await asyncio.sleep(delay)

    def ensure_ok(self, response: httpx.Response, ok_statuses: Tuple[int, ...] = (200, 201)) -> Dict[str, Any]:
        """Return the JSON body for a successful response, or raise a readable PlatformError."""
        if response.status_code not in ok_statuses:
            raise PlatformError(self._describe_failure(response), status_code=response.status_code)
        try:
            return response.json()
        except ValueError:
            raise PlatformError(
                f"Unexpected non-JSON response (HTTP {response.status_code}).",
                status_code=response.status_code,
            ) from None

    def error_detail(self, response: httpx.Response) -> Optional[str]:
        """Pull the platform's own error text out of a failed response. Subclasses may override."""
        try:
            body = response.json()
        except ValueError:
            text = response.text.strip()
            return text[:200] if text and "<html" not in text.lower() else None
        if isinstance(body, dict):
            for key in ("error", "message", "description", "detail", "errors"):
                value = body.get(key)
                if isinstance(value, str) and value:
                    return value
                if isinstance(value, list) and value:
                    return "; ".join(str(item) for item in value)
                if isinstance(value, dict) and value.get("message"):
                    return str(value["message"])
        return None

    def _describe_failure(self, response: httpx.Response) -> str:
        status = response.status_code
        detail = self.error_detail(response)
        if status == 401:
            prefix = "Authentication failed"
        elif status == 403:
            prefix = "Permission denied"
        elif status == 404:
            prefix = "Not found"
        elif status == 429:
            prefix = "Rate limited by the platform"
        elif status >= 500:
            prefix = "Platform is unavailable"
        else:
            prefix = "Rejected by the platform"
        message = f"{prefix} (HTTP {status})"
        return f"{message}: {detail}" if detail else f"{message}."


def derive_title(text: str, link: str, max_length: int = 70) -> str:
    """Build a headline from the message: drop the link, tidy punctuation, cut at a word boundary."""
    without_link = text.replace(link, " ")
    cleaned = re.sub(r"\s+", " ", without_link).strip(" -:|,.")
    if not cleaned:
        return "New update"

    first_sentence = re.split(r"(?<=[.!?])\s", cleaned, maxsplit=1)[0].rstrip(".!? ")
    candidate = first_sentence or cleaned
    if len(candidate) <= max_length:
        return candidate

    cut = candidate[: max_length + 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{cut}..."
