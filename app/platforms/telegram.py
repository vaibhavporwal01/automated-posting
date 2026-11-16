"""Telegram channel, through the Bot API.

Docs: https://core.telegram.org/bots/api#sendmessage
- Create a bot with @BotFather to get TELEGRAM_BOT_TOKEN.
- Add the bot as an admin of your channel and set TELEGRAM_CHAT_ID to the
  channel's @username (public) or numeric id (private).
- Public channels give a shareable https://t.me/<channel>/<id> link.
"""

from typing import Any, Dict

import httpx

from app.platforms.base import BasePlatform, PlatformError, Post, PublishedPost

API_BASE = "https://api.telegram.org"


class TelegramPlatform(BasePlatform):
    key = "telegram"
    name = "Telegram"
    docs_url = "https://core.telegram.org/bots/api#sendmessage"
    required_settings = ("telegram_bot_token", "telegram_chat_id")

    async def publish(self, post: Post) -> PublishedPost:
        token = self.secret("telegram_bot_token")
        response = await self.request(
            "POST",
            f"{API_BASE}/bot{token}/sendMessage",
            json={
                "chat_id": self._chat_id(),
                "text": post.text,
                "link_preview_options": {"url": post.link, "prefer_large_media": True},
            },
        )
        message = self._result(response)
        message_id = message.get("message_id")
        chat = message.get("chat") or {}
        if message_id is None:
            raise PlatformError("Telegram did not return a message id.")

        username = chat.get("username")
        if username:
            return PublishedPost(url=f"https://t.me/{username}/{message_id}", public=True)

        # Private chat or channel: the link only opens for members.
        chat_id = str(chat.get("id", ""))
        internal_id = chat_id[4:] if chat_id.startswith("-100") else chat_id.lstrip("-")
        return PublishedPost(url=f"https://t.me/c/{internal_id}/{message_id}", public=False)

    def _chat_id(self) -> str:
        chat_id = (self.settings.telegram_chat_id or "").strip()
        if chat_id.startswith("https://t.me/"):
            chat_id = "@" + chat_id.rsplit("/", 1)[-1]
        elif not chat_id.startswith("@") and not chat_id.lstrip("-").isdigit():
            chat_id = f"@{chat_id}"
        return chat_id

    def _result(self, response: httpx.Response) -> Dict[str, Any]:
        try:
            body = response.json()
        except ValueError:
            raise PlatformError(f"Unexpected non-JSON response (HTTP {response.status_code}).") from None
        if not body.get("ok"):
            raise PlatformError(self._describe_failure(response), status_code=response.status_code)
        return body.get("result") or {}

    def error_detail(self, response: httpx.Response):
        try:
            description = response.json().get("description")
        except ValueError:
            description = None
        if description and "chat not found" in description.lower():
            return f"{description}. Check TELEGRAM_CHAT_ID and that the bot is an admin of the channel"
        return description or super().error_detail(response)
