"""The posting service and the HTTP API, with stand-in platforms instead of real ones."""

import json
import re

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from app.platforms import BasePlatform, PlatformError, PublishedPost
from app.services.posting_service import PostingService, select_platforms

MESSAGE = "Check out our latest business platform and grow your online visibility. https://example.com"


class WorkingPlatform(BasePlatform):
    key = "working"
    name = "Working"
    docs_url = "https://example.com/docs"

    async def publish(self, post):
        return PublishedPost(url=f"https://posts.example.com/{self.name.lower()}/1", public=True)


class RejectingPlatform(BasePlatform):
    key = "rejecting"
    name = "Rejecting"
    docs_url = "https://example.com/docs"

    async def publish(self, post):
        raise PlatformError("Authentication failed (HTTP 401): Bad credentials", status_code=401)


class CrashingPlatform(BasePlatform):
    key = "crashing"
    name = "Crashing"
    docs_url = "https://example.com/docs"

    async def publish(self, post):
        raise KeyError("url")


def make_service(settings, client, *classes):
    return PostingService([cls(settings, client) for cls in classes], [], settings, client)


# ------------------------------------------------------------------ platform selection


def test_selection_skips_platforms_without_credentials(make_settings, client):
    selected, skipped = select_platforms(make_settings(github_token="t"), client)
    names = {platform.name for platform in selected}

    assert names == {"GitHub Gist", "Telegraph", "Write.as"}
    reasons = {item.platform: item.reason for item in skipped}
    assert reasons["Telegram"] == "Missing TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID"
    assert reasons["Dev.to"] == "Missing DEVTO_API_KEY"


def test_enabled_platforms_narrows_selection(make_settings, client):
    settings = make_settings(github_token="t", enabled_platforms="telegraph, github_gist")
    selected, _ = select_platforms(settings, client)
    assert sorted(platform.key for platform in selected) == ["github_gist", "telegraph"]


# ------------------------------------------------------------------ service behaviour


async def test_one_failure_does_not_stop_the_others(make_settings, client):
    service = make_service(make_settings(), client, WorkingPlatform, RejectingPlatform, CrashingPlatform)

    response = await service.publish(MESSAGE, "https://example.com")

    assert response.success is True
    assert response.summary.total == 3
    assert response.summary.succeeded == 1
    assert response.summary.failed == 2

    by_name = {result.platform: result for result in response.results}
    ok = by_name["Working"]
    assert ok.status == "success"
    assert ok.posted_url == "https://posts.example.com/working/1"
    assert ok.public_access is True
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", ok.date)
    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", ok.time)
    assert ok.error is None

    rejected = by_name["Rejecting"]
    assert rejected.status == "failed"
    assert rejected.posted_url is None
    assert rejected.public_access is False
    assert rejected.date is None and rejected.time is None
    assert rejected.error == "Authentication failed (HTTP 401): Bad credentials"

    assert by_name["Crashing"].error == "Unexpected error: KeyError: 'url'"


async def test_all_failures_mean_success_false(make_settings, client):
    service = make_service(make_settings(), client, RejectingPlatform)
    response = await service.publish(MESSAGE, "https://example.com")
    assert response.success is False
    assert response.summary.succeeded == 0


async def test_each_run_is_saved_as_json(make_settings, client, tmp_path):
    service = make_service(make_settings(runs_dir=str(tmp_path)), client, WorkingPlatform)
    response = await service.publish(MESSAGE, "https://example.com")

    (saved,) = list(tmp_path.glob(f"*-{response.run_id}.json"))
    record = json.loads(saved.read_text())
    assert record["message"] == MESSAGE
    assert record["response"]["results"][0]["platform"] == "Working"


@respx.mock
async def test_public_access_is_verified_by_opening_the_url(make_settings, client):
    respx.get("https://posts.example.com/working/1").respond(404)
    service = make_service(make_settings(verify_public_access=True), client, WorkingPlatform)
    response = await service.publish(MESSAGE, "https://example.com")
    assert response.results[0].status == "success"
    assert response.results[0].public_access is False


@respx.mock
async def test_inconclusive_public_check_keeps_platform_answer(make_settings, client):
    respx.get("https://posts.example.com/working/1").mock(side_effect=httpx.ConnectTimeout("slow"))
    service = make_service(make_settings(verify_public_access=True), client, WorkingPlatform)
    response = await service.publish(MESSAGE, "https://example.com")
    assert response.results[0].public_access is True


# ------------------------------------------------------------------ HTTP API


@pytest.fixture
def api(make_settings):
    """Yield (TestClient, install) where install(*platform classes) swaps in stand-in platforms."""
    app = create_app(make_settings())
    with TestClient(app) as test_client:
        def install(*classes):
            settings = app.state.settings
            http_client = app.state.service.client
            app.state.service = PostingService(
                [cls(settings, http_client) for cls in classes], [], settings, http_client
            )

        yield test_client, install


def test_posting_returns_results_for_every_platform(api):
    test_client, install = api
    install(WorkingPlatform, RejectingPlatform)

    response = test_client.post("/posting", json={"message": MESSAGE})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert [r["platform"] for r in body["results"]] == ["Working", "Rejecting"]
    assert set(body["results"][0]) == {"platform", "status", "posted_url", "public_access", "date", "time", "error"}


def test_posting_returns_502_when_every_platform_fails(api):
    test_client, install = api
    install(RejectingPlatform)
    response = test_client.post("/posting", json={"message": MESSAGE})
    assert response.status_code == 502
    assert response.json()["success"] is False


def test_posting_returns_503_without_platforms(api):
    test_client, install = api
    install()
    response = test_client.post("/posting", json={"message": MESSAGE})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "no_platforms"


@pytest.mark.parametrize(
    "payload, code, fragment",
    [
        ({"message": "x" * 190 + " https://a.com"}, "message_too_long", "must not exceed 200 characters"),
        ({"message": "No link in this one"}, "missing_link", "found none"),
        ({"message": "https://a.com and https://b.com"}, "multiple_links", "found 2"),
        ({"message": "Visit https://localhost:8000"}, "invalid_url", "full domain name"),
        ({"message": ""}, "empty_message", "must not be empty"),
        ({"message": 42}, "invalid_type", "must be a string"),
        ({}, "missing", "'message' field is required"),
        ({"message": MESSAGE, "platforms": ["devto"]}, "extra_forbidden", "selected by the server"),
    ],
)
def test_validation_errors_are_clear(api, payload, code, fragment):
    test_client, _ = api
    response = test_client.post("/posting", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"][0]["code"] == code
    assert fragment in body["error"]["message"]


def test_malformed_json_is_rejected(api):
    test_client, _ = api
    response = test_client.post("/posting", content=b"{not json", headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "The request body is not valid JSON."


def test_platform_listing_never_exposes_secrets(make_settings):
    app = create_app(make_settings(github_token="ghp_secret_value"))
    with TestClient(app) as test_client:
        response = test_client.get("/platforms")
    assert response.status_code == 200
    assert "ghp_secret_value" not in response.text
    gist = next(p for p in response.json() if p["key"] == "github_gist")
    assert gist["configured"] is True and gist["missing"] == []


def test_console_and_docs_are_served(api):
    test_client, _ = api
    assert test_client.get("/").status_code == 200
    assert test_client.get("/docs").status_code == 200
    assert test_client.get("/health").json()["status"] == "ok"
