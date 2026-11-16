"""Write.as, a minimalist blogging platform built on WriteFreely.

Docs: https://developers.write.as/docs/api/#publish-a-post
- POST /api/posts creates a post. Without authentication the post is
  anonymous, so this platform also works with zero configuration.
- Write.as unpublishes anonymous posts after about one hour. Set
  WRITEAS_ACCESS_TOKEN (from POST /api/auth/login) to post as a user and keep
  posts online.
"""

import logging
from typing import Dict

from app.platforms.base import BasePlatform, PlatformError, Post, PublishedPost

logger = logging.getLogger("posting.platforms")

API_BASE = "https://write.as/api"
PUBLIC_BASE = "https://write.as"


class WriteAsPlatform(BasePlatform):
    key = "writeas"
    name = "Write.as"
    docs_url = "https://developers.write.as/docs/api/"
    required_settings = ()

    async def publish(self, post: Post) -> PublishedPost:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        anonymous = not self.settings.writeas_access_token
        if not anonymous:
            headers["Authorization"] = f"Token {self.secret('writeas_access_token')}"

        body_markdown = post.text.replace(post.link, f"[{post.link}]({post.link})")
        response = await self.request(
            "POST",
            f"{API_BASE}/posts",
            headers=headers,
            json={"title": post.title, "body": body_markdown, "font": "sans"},
        )
        data = self.ensure_ok(response).get("data") or {}
        post_id = data.get("id")
        if not post_id:
            raise PlatformError("Write.as did not return a post id.")

        if anonymous:
            logger.warning(
                "platform=Write.as posted anonymously; Write.as unpublishes anonymous posts after about an hour. "
                "Set WRITEAS_ACCESS_TOKEN to keep posts online"
            )
        return PublishedPost(url=f"{PUBLIC_BASE}/{post_id}", public=True)

    def error_detail(self, response):
        try:
            body = response.json()
        except ValueError:
            return super().error_detail(response)
        return body.get("error_msg") or super().error_detail(response)
