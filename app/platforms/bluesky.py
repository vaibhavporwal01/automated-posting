"""Bluesky, through the AT Protocol XRPC API.

Docs:
- Creating a post: https://docs.bsky.app/docs/advanced-guides/posts
- Rich text links (facets): https://docs.bsky.app/docs/advanced-guides/post-richtext
- com.atproto.server.createSession: https://docs.bsky.app/docs/api/com-atproto-server-create-session

Needs your handle and an app password (Settings > Privacy and security > App
passwords). The link is sent as a facet so it is clickable, and Bluesky counts
facet positions in UTF-8 bytes, not characters.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx

from app.platforms.base import BasePlatform, PlatformError, Post, PublishedPost


class BlueskyPlatform(BasePlatform):
    key = "bluesky"
    name = "Bluesky"
    docs_url = "https://docs.bsky.app/docs/advanced-guides/posts"
    required_settings = ("bluesky_handle", "bluesky_app_password")

    async def publish(self, post: Post) -> PublishedPost:
        service = self.settings.bluesky_service.rstrip("/")
        session = await self._create_session(service)

        record: Dict[str, Any] = {
            "$type": "app.bsky.feed.post",
            "text": post.text,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "langs": ["en"],
            "facets": self._link_facets(post),
        }
        response = await self.request(
            "POST",
            f"{service}/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {session['accessJwt']}"},
            json={"repo": session["did"], "collection": "app.bsky.feed.post", "record": record},
        )
        body = self.ensure_ok(response, ok_statuses=(200,))
        uri = body.get("uri", "")
        record_key = uri.rsplit("/", 1)[-1] if uri.startswith("at://") else None
        if not record_key:
            raise PlatformError("Bluesky did not return a post URI.")
        handle = session.get("handle") or self.settings.bluesky_handle
        return PublishedPost(url=f"https://bsky.app/profile/{handle}/post/{record_key}", public=True)

    async def _create_session(self, service: str) -> Dict[str, Any]:
        response = await self.request(
            "POST",
            f"{service}/xrpc/com.atproto.server.createSession",
            json={
                "identifier": self.settings.bluesky_handle.lstrip("@"),
                "password": self.secret("bluesky_app_password"),
            },
        )
        session = self.ensure_ok(response, ok_statuses=(200,))
        if not session.get("accessJwt") or not session.get("did"):
            raise PlatformError("Bluesky did not return a session.")
        return session

    @staticmethod
    def _link_facets(post: Post) -> List[Dict[str, Any]]:
        start_char = post.text.find(post.link)
        if start_char < 0:
            return []
        byte_start = len(post.text[:start_char].encode("utf-8"))
        byte_end = byte_start + len(post.link.encode("utf-8"))
        return [
            {
                "index": {"byteStart": byte_start, "byteEnd": byte_end},
                "features": [{"$type": "app.bsky.richtext.facet#link", "uri": post.link}],
            }
        ]

    def error_detail(self, response: httpx.Response):
        try:
            body = response.json()
        except ValueError:
            return super().error_detail(response)
        error, message = body.get("error"), body.get("message")
        if error and message:
            return f"{error}: {message}"
        return message or error or super().error_detail(response)
