"""DEV Community (dev.to), running on the Forem platform.

Docs: https://developers.forem.com/api/v1#tag/articles/operation/createArticle
- Needs an API key from https://dev.to/settings/extensions, sent in the
  "api-key" header.
- Publishes an article immediately (published: true).
"""

import re
from typing import List

from app.platforms.base import BasePlatform, PlatformError, Post, PublishedPost

API_URL = "https://dev.to/api/articles"


class DevToPlatform(BasePlatform):
    key = "devto"
    name = "Dev.to"
    docs_url = "https://developers.forem.com/api/v1#tag/articles/operation/createArticle"
    required_settings = ("devto_api_key",)

    async def publish(self, post: Post) -> PublishedPost:
        body_markdown = post.text.replace(post.link, f"[{post.link}]({post.link})")
        response = await self.request(
            "POST",
            API_URL,
            headers={
                "api-key": self.secret("devto_api_key"),
                "Accept": "application/vnd.forem.api-v1+json",
                "Content-Type": "application/json",
            },
            json={
                "article": {
                    "title": post.title,
                    "body_markdown": body_markdown,
                    "published": True,
                    "tags": self._tags(),
                }
            },
        )
        body = self.ensure_ok(response, ok_statuses=(200, 201))
        url = body.get("url")
        if not url:
            raise PlatformError("Dev.to did not return an article URL.")
        return PublishedPost(url=url, public=bool(body.get("published", True)))

    def _tags(self) -> List[str]:
        # Forem allows at most 4 tags, lowercase alphanumeric only.
        tags = []
        for raw in self.settings.devto_tags.split(","):
            tag = re.sub(r"[^a-z0-9]", "", raw.lower())
            if tag and tag not in tags:
                tags.append(tag)
        return tags[:4]
