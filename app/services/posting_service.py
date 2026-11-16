"""Fan a message out to every selected platform and collect one result per platform."""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Sequence, Tuple
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings
from app.platforms import PLATFORM_CLASSES, BasePlatform, PlatformError, Post
from app.schemas import PlatformResult, PostingResponse, PostingSummary, SkippedPlatform

logger = logging.getLogger("posting.service")

PUBLIC_CHECK_USER_AGENT = "Mozilla/5.0 (compatible; automated-posting-public-check/1.0)"
# The public check is a courtesy; it should not hold the whole response hostage.
PUBLIC_CHECK_TIMEOUT_SECONDS = 6.0


def select_platforms(
    settings: Settings, client: httpx.AsyncClient
) -> Tuple[List[BasePlatform], List[SkippedPlatform]]:
    """Decide which platforms to post to.

    Every registered platform is used when its credentials are present. The
    optional ENABLED_PLATFORMS setting narrows the list further.
    """
    enabled_keys = settings.enabled_platform_keys
    selected: List[BasePlatform] = []
    skipped: List[SkippedPlatform] = []

    for cls in PLATFORM_CLASSES:
        if enabled_keys is not None and cls.key not in enabled_keys:
            continue
        missing = cls.missing_settings(settings)
        if missing:
            skipped.append(SkippedPlatform(platform=cls.name, reason=f"Missing {', '.join(missing)}"))
            continue
        selected.append(cls(settings, client))

    return selected, skipped


class PostingService:
    def __init__(
        self,
        platforms: Sequence[BasePlatform],
        skipped: Sequence[SkippedPlatform],
        settings: Settings,
        client: httpx.AsyncClient,
    ) -> None:
        self.platforms = list(platforms)
        self.skipped = list(skipped)
        self.settings = settings
        self.client = client
        self.tz = ZoneInfo(settings.timezone)

    async def publish(self, message: str, link: str) -> PostingResponse:
        run_id = uuid.uuid4().hex[:8]
        post = Post(text=message, link=link)
        started = time.perf_counter()
        logger.info(
            "run=%s start platforms=%s link=%s chars=%s",
            run_id, ",".join(p.name for p in self.platforms), link, len(message),
        )

        # Each platform runs in its own task, so one failure or slow API never blocks the rest.
        results = await asyncio.gather(*(self._publish_one(run_id, platform, post) for platform in self.platforms))

        succeeded = sum(1 for result in results if result.status == "success")
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "run=%s done succeeded=%s failed=%s duration_ms=%s",
            run_id, succeeded, len(results) - succeeded, duration_ms,
        )
        response = PostingResponse(
            success=succeeded > 0,
            run_id=run_id,
            timezone=self.settings.timezone,
            summary=PostingSummary(
                total=len(results), succeeded=succeeded, failed=len(results) - succeeded, duration_ms=duration_ms
            ),
            results=list(results),
            skipped=self.skipped,
        )
        self._save_run(message, response)
        return response

    def _save_run(self, message: str, response: PostingResponse) -> None:
        """Keep a JSON record of every run next to the logs, for auditing what went where."""
        if not self.settings.runs_dir:
            return
        try:
            folder = Path(self.settings.runs_dir)
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(self.tz).strftime("%Y%m%d-%H%M%S")
            record = {"message": message, "response": response.model_dump()}
            (folder / f"{stamp}-{response.run_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        except OSError:
            logger.warning("run=%s could not save the run record", response.run_id, exc_info=True)

    async def _publish_one(self, run_id: str, platform: BasePlatform, post: Post) -> PlatformResult:
        started = time.perf_counter()
        # Hard ceiling per platform: every attempt plus backoff, with a little headroom.
        budget = self.settings.request_timeout * (self.settings.max_retries + 1) * 2 + 5
        try:
            published = await asyncio.wait_for(platform.publish(post), timeout=budget)
        except PlatformError as exc:
            return self._failed(run_id, platform, exc.message, started)
        except asyncio.TimeoutError:
            return self._failed(run_id, platform, f"Gave up after {budget:g}s without a response.", started)
        except Exception as exc:  # an integration bug must not take down the whole run
            logger.exception("run=%s platform=%s unexpected error", run_id, platform.name)
            return self._failed(run_id, platform, f"Unexpected error: {type(exc).__name__}: {exc}", started)

        posted_at = datetime.now(self.tz)
        public = published.public and await self._is_publicly_reachable(published.url, default=published.public)
        logger.info(
            "run=%s platform=%s status=success url=%s public=%s elapsed_ms=%s",
            run_id, platform.name, published.url, public, _elapsed_ms(started),
        )
        return PlatformResult(
            platform=platform.name,
            status="success",
            posted_url=published.url,
            public_access=public,
            date=posted_at.strftime("%Y-%m-%d"),
            time=posted_at.strftime("%H:%M:%S"),
            error=None,
        )

    async def _is_publicly_reachable(self, url: str, default: bool) -> bool:
        """Open the URL with no credentials. 2xx means public; 401/404/410 means not.

        Anything inconclusive (timeouts, 5xx, a 403 from bot protection) falls
        back to what the platform reported, so a flaky check never hides a real post.
        """
        if not self.settings.verify_public_access:
            return default
        try:
            response = await self.client.get(
                url,
                headers={"User-Agent": PUBLIC_CHECK_USER_AGENT},
                follow_redirects=True,
                timeout=min(self.settings.request_timeout, PUBLIC_CHECK_TIMEOUT_SECONDS),
            )
        except httpx.HTTPError:
            logger.info("public check for %s was inconclusive; keeping the platform's answer", url)
            return default
        if 200 <= response.status_code < 300:
            return True
        if response.status_code in (401, 404, 410):
            return False
        return default

    def _failed(self, run_id: str, platform: BasePlatform, error: str, started: float) -> PlatformResult:
        logger.warning(
            "run=%s platform=%s status=failed error=%r elapsed_ms=%s",
            run_id, platform.name, error, _elapsed_ms(started),
        )
        return PlatformResult(
            platform=platform.name,
            status="failed",
            posted_url=None,
            public_access=False,
            date=None,
            time=None,
            error=error,
        )


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def build_service(settings: Settings, client: httpx.AsyncClient) -> PostingService:
    platforms, skipped = select_platforms(settings, client)
    return PostingService(platforms, skipped, settings, client)


__all__ = ["PostingService", "build_service", "select_platforms"]
