"""GitHub Gist.

Docs: https://docs.github.com/en/rest/gists/gists#create-a-gist
- Needs a personal access token with the "gist" scope (classic) or the
  "Gists: read and write" account permission (fine-grained).
- Creates a public gist containing the message as Markdown.
"""

from datetime import datetime, timezone

from app.platforms.base import BasePlatform, PlatformError, Post, PublishedPost

API_URL = "https://api.github.com/gists"


class GitHubGistPlatform(BasePlatform):
    key = "github_gist"
    name = "GitHub Gist"
    docs_url = "https://docs.github.com/en/rest/gists/gists#create-a-gist"
    required_settings = ("github_token",)

    async def publish(self, post: Post) -> PublishedPost:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        content = f"# {post.title}\n\n{post.text.replace(post.link, f'[{post.link}]({post.link})')}\n"
        response = await self.request(
            "POST",
            API_URL,
            headers={
                "Authorization": f"Bearer {self.secret('github_token')}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "description": post.title,
                "public": True,
                "files": {f"post-{stamp}.md": {"content": content}},
            },
        )
        body = self.ensure_ok(response, ok_statuses=(201,))
        url = body.get("html_url")
        if not url:
            raise PlatformError("GitHub did not return a gist URL.")
        return PublishedPost(url=url, public=bool(body.get("public", True)))
