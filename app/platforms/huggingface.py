"""Hugging Face Hub, the main platform for sharing LLMs, datasets and demos.

Docs:
- Hub HTTP API: https://huggingface.co/docs/hub/api
- Discussions: https://huggingface.co/docs/huggingface_hub/guides/community

The message is published as a public discussion on a repo you own. On first
use the integration looks up your username, creates the repo if it does not
exist yet (HF_REPO_ID, default <user>/automated-posting-feed), then opens a
discussion with the message. Setup results are cached for the process.
"""

from typing import Dict, Optional

from app.platforms.base import BasePlatform, PlatformError, Post, PublishedPost

HUB = "https://huggingface.co"
DEFAULT_REPO_NAME = "automated-posting-feed"
_REPO_TYPE_PREFIX = {"model": "", "dataset": "datasets/", "space": "spaces/"}


class HuggingFacePlatform(BasePlatform):
    key = "huggingface"
    name = "Hugging Face"
    docs_url = "https://huggingface.co/docs/hub/api"
    required_settings = ("hf_token",)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._username: Optional[str] = None
        self._repo_private: Dict[str, bool] = {}

    async def publish(self, post: Post) -> PublishedPost:
        repo_type = self.settings.hf_repo_type.lower()
        if repo_type not in _REPO_TYPE_PREFIX:
            raise PlatformError(f"HF_REPO_TYPE must be one of model, dataset, space (got '{repo_type}').")

        repo_id = self.settings.hf_repo_id or f"{await self._whoami()}/{DEFAULT_REPO_NAME}"
        private = await self._ensure_repo(repo_id, repo_type)

        description = post.text.replace(post.link, f"[{post.link}]({post.link})")
        response = await self.request(
            "POST",
            f"{HUB}/api/{repo_type}s/{repo_id}/discussions",
            headers=self._headers(),
            json={"title": post.title, "description": description, "pullRequest": False},
        )
        body = self.ensure_ok(response, ok_statuses=(200, 201))
        number = body.get("num")
        if number is None:
            raise PlatformError("Hugging Face did not return a discussion number.")
        url = f"{HUB}/{_REPO_TYPE_PREFIX[repo_type]}{repo_id}/discussions/{number}"
        return PublishedPost(url=url, public=not private)

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.secret('hf_token')}"}

    async def _whoami(self) -> str:
        if self._username is None:
            response = await self.request("GET", f"{HUB}/api/whoami-v2", headers=self._headers())
            name = self.ensure_ok(response, ok_statuses=(200,)).get("name")
            if not name:
                raise PlatformError("Could not read the Hugging Face username for this token.")
            self._username = name
        return self._username

    async def _ensure_repo(self, repo_id: str, repo_type: str) -> bool:
        """Make sure the repo exists. Returns True when it is private."""
        cache_key = f"{repo_type}:{repo_id}"
        if cache_key in self._repo_private:
            return self._repo_private[cache_key]

        info = await self.request("GET", f"{HUB}/api/{repo_type}s/{repo_id}", headers=self._headers())
        if info.status_code == 200:
            private = bool(info.json().get("private", False))
        elif info.status_code in (401, 404):
            # The Hub answers 401 or 404 for a repo that does not exist yet.
            await self._create_repo(repo_id, repo_type)
            private = False
        else:
            raise PlatformError(self._describe_failure(info), status_code=info.status_code)

        self._repo_private[cache_key] = private
        return private

    async def _create_repo(self, repo_id: str, repo_type: str) -> None:
        namespace, _, name = repo_id.partition("/")
        if not name:
            raise PlatformError(f"HF_REPO_ID must look like owner/name (got '{repo_id}').")
        payload = {"name": name, "type": repo_type, "private": False}
        if namespace != await self._whoami():
            payload["organization"] = namespace

        created = await self.request("POST", f"{HUB}/api/repos/create", headers=self._headers(), json=payload)
        if created.status_code not in (200, 201, 409):  # 409: created meanwhile, fine
            raise PlatformError(
                f"Could not create repo {repo_id}. {self._describe_failure(created)}",
                status_code=created.status_code,
            )
