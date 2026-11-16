"""Telegraph (telegra.ph), Telegram's anonymous publishing platform.

Docs: https://telegra.ph/api
- createAccount gives an access token without any sign-up, so this platform
  works with zero configuration. Set TELEGRAPH_ACCESS_TOKEN to keep every page
  under one account across restarts.
- createPage publishes a page and returns its public URL.
"""

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.platforms.base import BasePlatform, PlatformError, Post, PublishedPost

logger = logging.getLogger("posting.platforms")

API_BASE = "https://api.telegra.ph"


class TelegraphPlatform(BasePlatform):
    key = "telegraph"
    name = "Telegraph"
    docs_url = "https://telegra.ph/api"
    required_settings = ()

    # Token created on first use, shared by every request in this process.
    # Two concurrent first requests may each create an account; that is harmless.
    _provisioned_token: Optional[str] = None

    async def publish(self, post: Post) -> PublishedPost:
        token = await self._access_token()
        payload = {
            "access_token": token,
            "title": post.title,
            "author_name": self.settings.telegraph_author_name,
            "content": json.dumps(self._content_nodes(post)),
            "return_content": "false",
        }
        response = await self.request("POST", f"{API_BASE}/createPage", data=payload)
        result = self._result(response)
        url = result.get("url")
        if not url:
            raise PlatformError("Telegraph did not return a page URL.")
        return PublishedPost(url=url, public=True)

    @staticmethod
    def _content_nodes(post: Post) -> List[Dict[str, Any]]:
        """Telegraph content is a DOM-like node list. Render the message with a clickable link."""
        before, _, after = post.text.partition(post.link)
        children: List[Any] = []
        if before:
            children.append(before)
        children.append({"tag": "a", "attrs": {"href": post.link}, "children": [post.link]})
        if after:
            children.append(after)
        return [{"tag": "p", "children": children}]

    async def _access_token(self) -> str:
        if self.settings.telegraph_access_token:
            return self.secret("telegraph_access_token")

        cls = type(self)
        if cls._provisioned_token is None:
            response = await self.request(
                "POST",
                f"{API_BASE}/createAccount",
                data={
                    "short_name": "automated-posting",
                    "author_name": self.settings.telegraph_author_name,
                },
            )
            token = self._result(response).get("access_token")
            if not token:
                raise PlatformError("Telegraph did not return an access token.")
            cls._provisioned_token = token
            logger.info(
                "platform=Telegraph created a new account; set TELEGRAPH_ACCESS_TOKEN to reuse it across restarts"
            )
        return cls._provisioned_token

    def _result(self, response: httpx.Response) -> Dict[str, Any]:
        body = self.ensure_ok(response, ok_statuses=(200,))
        if not body.get("ok"):
            error = body.get("error") or "unknown error"
            if error in ("ACCESS_TOKEN_INVALID", "UNAUTHORIZED"):
                raise PlatformError(f"Authentication failed: {error}")
            raise PlatformError(f"Rejected by the platform: {error}")
        return body.get("result") or {}
