"""Each integration against a mocked HTTP layer: request shape, URL parsing and error mapping."""

import json

import httpx
import pytest
import respx

from app.platforms import PlatformError, Post
from app.platforms.bluesky import BlueskyPlatform
from app.platforms.devto import DevToPlatform
from app.platforms.github_gist import GitHubGistPlatform
from app.platforms.huggingface import HuggingFacePlatform
from app.platforms.telegram import TelegramPlatform
from app.platforms.telegraph import TelegraphPlatform
from app.platforms.writeas import WriteAsPlatform

POST = Post(
    text="Check out our latest business platform and grow your online visibility. https://example.com",
    link="https://example.com",
)


def test_title_is_derived_from_message_without_link():
    assert POST.title == "Check out our latest business platform and grow your online visibility"


def test_long_title_is_cut_at_a_word_boundary():
    post = Post(text="word " * 30 + "https://example.com", link="https://example.com")
    assert len(post.title) <= 73
    assert post.title.endswith("...")
    assert "  " not in post.title


# ------------------------------------------------------------------ Telegraph


@respx.mock
async def test_telegraph_creates_account_then_page(make_settings, client, monkeypatch):
    monkeypatch.setattr(TelegraphPlatform, "_provisioned_token", None)
    account = respx.post("https://api.telegra.ph/createAccount").respond(
        json={"ok": True, "result": {"access_token": "tok123"}}
    )
    page = respx.post("https://api.telegra.ph/createPage").respond(
        json={"ok": True, "result": {"url": "https://telegra.ph/Check-out-11-16"}}
    )

    published = await TelegraphPlatform(make_settings(), client).publish(POST)

    assert published.url == "https://telegra.ph/Check-out-11-16"
    assert published.public is True
    assert account.called
    form = dict(httpx.QueryParams(page.calls.last.request.content.decode()))
    assert form["access_token"] == "tok123"
    nodes = json.loads(form["content"])
    assert nodes[0]["children"][1] == {
        "tag": "a",
        "attrs": {"href": "https://example.com"},
        "children": ["https://example.com"],
    }


@respx.mock
async def test_telegraph_uses_configured_token(make_settings, client):
    account = respx.post("https://api.telegra.ph/createAccount")
    respx.post("https://api.telegra.ph/createPage").respond(
        json={"ok": True, "result": {"url": "https://telegra.ph/x"}}
    )
    settings = make_settings(telegraph_access_token="mine")
    await TelegraphPlatform(settings, client).publish(POST)
    assert not account.called


@respx.mock
async def test_telegraph_reports_api_error(make_settings, client):
    respx.post("https://api.telegra.ph/createPage").respond(json={"ok": False, "error": "ACCESS_TOKEN_INVALID"})
    with pytest.raises(PlatformError, match="Authentication failed: ACCESS_TOKEN_INVALID"):
        await TelegraphPlatform(make_settings(telegraph_access_token="bad"), client).publish(POST)


# ------------------------------------------------------------------ Write.as


@respx.mock
async def test_writeas_anonymous_post(make_settings, client):
    route = respx.post("https://write.as/api/posts").respond(
        201, json={"code": 201, "data": {"id": "rf3t35fkax0aw", "token": "edit-token"}}
    )
    published = await WriteAsPlatform(make_settings(), client).publish(POST)

    assert published.url == "https://write.as/rf3t35fkax0aw"
    request = route.calls.last.request
    assert "Authorization" not in request.headers
    assert "[https://example.com](https://example.com)" in json.loads(request.content)["body"]


@respx.mock
async def test_writeas_error_message(make_settings, client):
    respx.post("https://write.as/api/posts").respond(429, json={"code": 429, "error_msg": "Slow down."})
    with pytest.raises(PlatformError, match=r"Rate limited by the platform \(HTTP 429\): Slow down."):
        await WriteAsPlatform(make_settings(), client).publish(POST)


# ------------------------------------------------------------------ GitHub Gist


@respx.mock
async def test_gist_created_public(make_settings, client):
    route = respx.post("https://api.github.com/gists").respond(
        201, json={"html_url": "https://gist.github.com/vaibhav/abc", "public": True}
    )
    published = await GitHubGistPlatform(make_settings(github_token="ghp_x"), client).publish(POST)

    assert published.url == "https://gist.github.com/vaibhav/abc"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer ghp_x"
    body = json.loads(request.content)
    assert body["public"] is True
    (content,) = [f["content"] for f in body["files"].values()]
    assert content.startswith("# Check out our latest")


@respx.mock
async def test_gist_bad_credentials(make_settings, client):
    respx.post("https://api.github.com/gists").respond(401, json={"message": "Bad credentials"})
    with pytest.raises(PlatformError, match=r"Authentication failed \(HTTP 401\): Bad credentials"):
        await GitHubGistPlatform(make_settings(github_token="nope"), client).publish(POST)


def test_gist_needs_token(make_settings):
    assert GitHubGistPlatform.missing_settings(make_settings()) == ["GITHUB_TOKEN"]


# ------------------------------------------------------------------ Dev.to


@respx.mock
async def test_devto_publishes_article(make_settings, client):
    route = respx.post("https://dev.to/api/articles").respond(
        201, json={"url": "https://dev.to/vaibhav/check-out-1abc", "published": True}
    )
    settings = make_settings(devto_api_key="key", devto_tags="Python, Fast-API ,python,automation,extra,more")
    published = await DevToPlatform(settings, client).publish(POST)

    assert published.url == "https://dev.to/vaibhav/check-out-1abc"
    request = route.calls.last.request
    assert request.headers["api-key"] == "key"
    article = json.loads(request.content)["article"]
    assert article["published"] is True
    assert article["tags"] == ["python", "fastapi", "automation", "extra"]


@respx.mock
async def test_devto_validation_error(make_settings, client):
    respx.post("https://dev.to/api/articles").respond(
        422, json={"error": "Title has already been used in the last five minutes", "status": 422}
    )
    with pytest.raises(PlatformError, match="Rejected by the platform \\(HTTP 422\\): Title has already"):
        await DevToPlatform(make_settings(devto_api_key="key"), client).publish(POST)


# ------------------------------------------------------------------ Hugging Face


@respx.mock
async def test_huggingface_creates_repo_then_discussion(make_settings, client):
    respx.get("https://huggingface.co/api/whoami-v2").respond(json={"name": "vaibhav"})
    respx.get("https://huggingface.co/api/datasets/vaibhav/automated-posting-feed").respond(404, json={})
    create = respx.post("https://huggingface.co/api/repos/create").respond(
        200, json={"url": "https://huggingface.co/datasets/vaibhav/automated-posting-feed"}
    )
    discussion = respx.post(
        "https://huggingface.co/api/datasets/vaibhav/automated-posting-feed/discussions"
    ).respond(200, json={"num": 3})

    platform = HuggingFacePlatform(make_settings(hf_token="hf_x"), client)
    published = await platform.publish(POST)

    assert published.url == "https://huggingface.co/datasets/vaibhav/automated-posting-feed/discussions/3"
    assert published.public is True
    assert json.loads(create.calls.last.request.content) == {
        "name": "automated-posting-feed",
        "type": "dataset",
        "private": False,
    }
    body = json.loads(discussion.calls.last.request.content)
    assert body["pullRequest"] is False
    assert body["title"] == POST.title

    # Setup is cached: a second post goes straight to the discussions endpoint.
    await platform.publish(POST)
    assert create.call_count == 1


@respx.mock
async def test_huggingface_private_repo_is_not_public(make_settings, client):
    respx.get("https://huggingface.co/api/models/vaibhav/notes").respond(json={"private": True})
    respx.post("https://huggingface.co/api/models/vaibhav/notes/discussions").respond(json={"num": 1})
    settings = make_settings(hf_token="hf_x", hf_repo_id="vaibhav/notes", hf_repo_type="model")
    published = await HuggingFacePlatform(settings, client).publish(POST)
    assert published.url == "https://huggingface.co/vaibhav/notes/discussions/1"
    assert published.public is False


@respx.mock
async def test_huggingface_bad_token(make_settings, client):
    respx.get("https://huggingface.co/api/whoami-v2").respond(
        401, json={"error": "Invalid credentials in Authorization header"}
    )
    with pytest.raises(PlatformError, match="Authentication failed \\(HTTP 401\\): Invalid credentials"):
        await HuggingFacePlatform(make_settings(hf_token="bad"), client).publish(POST)


# ------------------------------------------------------------------ Telegram


TELEGRAM_URL = "https://api.telegram.org/bot123:abc/sendMessage"


@respx.mock
async def test_telegram_public_channel_link(make_settings, client):
    route = respx.post(TELEGRAM_URL).respond(
        json={
            "ok": True,
            "result": {"message_id": 42, "chat": {"id": -1001, "username": "dxoratest", "type": "channel"}},
        }
    )
    settings = make_settings(telegram_bot_token="123:abc", telegram_chat_id="dxoratest")
    published = await TelegramPlatform(settings, client).publish(POST)

    assert published.url == "https://t.me/dxoratest/42"
    assert published.public is True
    assert json.loads(route.calls.last.request.content)["chat_id"] == "@dxoratest"


@respx.mock
async def test_telegram_private_channel_link(make_settings, client):
    respx.post(TELEGRAM_URL).respond(
        json={"ok": True, "result": {"message_id": 7, "chat": {"id": -1003836584918, "type": "channel"}}}
    )
    settings = make_settings(telegram_bot_token="123:abc", telegram_chat_id="-1003836584918")
    published = await TelegramPlatform(settings, client).publish(POST)
    assert published.url == "https://t.me/c/3836584918/7"
    assert published.public is False


@respx.mock
async def test_telegram_chat_not_found_hint(make_settings, client):
    respx.post(TELEGRAM_URL).respond(
        400, json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}
    )
    settings = make_settings(telegram_bot_token="123:abc", telegram_chat_id="@missing")
    with pytest.raises(PlatformError, match="bot is an admin"):
        await TelegramPlatform(settings, client).publish(POST)


# ------------------------------------------------------------------ Bluesky

BSKY = "https://bsky.social/xrpc"


@respx.mock
async def test_bluesky_posts_with_clickable_link(make_settings, client):
    session = respx.post(f"{BSKY}/com.atproto.server.createSession").respond(
        json={"accessJwt": "jwt", "did": "did:plc:abc", "handle": "vaibhav.bsky.social"}
    )
    create = respx.post(f"{BSKY}/com.atproto.repo.createRecord").respond(
        json={"uri": "at://did:plc:abc/app.bsky.feed.post/3lbx7k2", "cid": "bafy"}
    )
    # A non-ASCII character before the link proves offsets are counted in UTF-8 bytes.
    post = Post(text="Café launch: https://example.com", link="https://example.com")
    settings = make_settings(bluesky_handle="@vaibhav.bsky.social", bluesky_app_password="app-pass")

    published = await BlueskyPlatform(settings, client).publish(post)

    assert published.url == "https://bsky.app/profile/vaibhav.bsky.social/post/3lbx7k2"
    assert json.loads(session.calls.last.request.content)["identifier"] == "vaibhav.bsky.social"
    request = create.calls.last.request
    assert request.headers["Authorization"] == "Bearer jwt"
    body = json.loads(request.content)
    assert body["repo"] == "did:plc:abc"
    assert body["collection"] == "app.bsky.feed.post"
    (facet,) = body["record"]["facets"]
    assert facet["index"] == {"byteStart": 14, "byteEnd": 33}
    assert facet["features"][0]["uri"] == "https://example.com"
    assert body["record"]["createdAt"].endswith("Z")


@respx.mock
async def test_bluesky_bad_app_password(make_settings, client):
    respx.post(f"{BSKY}/com.atproto.server.createSession").respond(
        401, json={"error": "AuthenticationRequired", "message": "Invalid identifier or password"}
    )
    settings = make_settings(bluesky_handle="v.bsky.social", bluesky_app_password="wrong")
    with pytest.raises(PlatformError, match="AuthenticationRequired: Invalid identifier or password"):
        await BlueskyPlatform(settings, client).publish(POST)


# ------------------------------------------------------------------ shared HTTP behaviour


@respx.mock
async def test_transient_error_is_retried(make_settings, client):
    route = respx.post("https://api.github.com/gists").mock(
        side_effect=[
            httpx.Response(503, json={"message": "Service unavailable"}),
            httpx.Response(201, json={"html_url": "https://gist.github.com/v/1", "public": True}),
        ]
    )
    settings = make_settings(github_token="t", max_retries=1)
    published = await GitHubGistPlatform(settings, client).publish(POST)
    assert published.url == "https://gist.github.com/v/1"
    assert route.call_count == 2


@respx.mock
async def test_timeout_becomes_readable_error(make_settings, client):
    respx.post("https://dev.to/api/articles").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(PlatformError, match="timed out after 5s"):
        await DevToPlatform(make_settings(devto_api_key="k"), client).publish(POST)


@respx.mock
async def test_connection_error_names_the_host(make_settings, client):
    respx.post("https://write.as/api/posts").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(PlatformError, match="Could not reach write.as"):
        await WriteAsPlatform(make_settings(), client).publish(POST)
