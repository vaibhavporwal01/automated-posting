import pytest

from app.validation import MessageValidationError, extract_links, validate_message, validate_url

EXAMPLE = "Check out our latest business platform and grow your online visibility. https://example.com"


def test_example_from_brief_is_valid():
    assert validate_message(EXAMPLE) == EXAMPLE


def test_surrounding_whitespace_is_trimmed():
    assert validate_message(f"   {EXAMPLE}\n") == EXAMPLE


@pytest.mark.parametrize("raw", ["", "   ", "\n\t"])
def test_empty_message_is_rejected(raw):
    with pytest.raises(MessageValidationError) as err:
        validate_message(raw)
    assert err.value.code == "empty_message"


def test_exactly_200_characters_is_allowed():
    link = "https://example.com"
    message = "a" * (200 - len(link) - 1) + " " + link
    assert len(message) == 200
    assert validate_message(message) == message


def test_201_characters_is_rejected():
    link = "https://example.com"
    message = "a" * (201 - len(link) - 1) + " " + link
    with pytest.raises(MessageValidationError) as err:
        validate_message(message)
    assert err.value.code == "message_too_long"
    assert "got 201" in err.value.message


def test_message_without_link_is_rejected():
    with pytest.raises(MessageValidationError) as err:
        validate_message("Grow your online visibility today")
    assert err.value.code == "missing_link"


@pytest.mark.parametrize(
    "message",
    [
        "Two links https://a.com and https://b.com",
        "One with scheme https://a.com and one without www.b.com",
    ],
)
def test_more_than_one_link_is_rejected(message):
    with pytest.raises(MessageValidationError) as err:
        validate_message(message)
    assert err.value.code == "multiple_links"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Visit https://example.com.", ["https://example.com"]),
        ("(see https://example.com/path?q=1)", ["https://example.com/path?q=1"]),
        ("Quoted 'https://example.com/a'!", ["https://example.com/a"]),
        ("No link at all", []),
        ("Bare www.example.com counts", ["www.example.com"]),
    ],
)
def test_extract_links_strips_trailing_punctuation(text, expected):
    assert extract_links(text) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://sub.example.co.in/path?x=1#top",
        "https://example.com:8443/a",
        "https://münchen.de",
        "https://8.8.8.8/dns",
    ],
)
def test_valid_urls(url):
    assert validate_url(url) == url


@pytest.mark.parametrize(
    "url, fragment",
    [
        ("ftp://files.example.com", "unsupported scheme"),
        ("www.example.com", "must start with http"),
        ("https://localhost:3000", "full domain name"),
        ("https://example", "full domain name"),
        ("https://192.168.1.10/admin", "private address"),
        ("https://127.0.0.1", "private address"),
        ("https://user:secret@example.com", "username or password"),
        ("https://exa_mple.com", "invalid host name"),
        ("https://-bad-.com", "invalid host name"),
        ("https://example.123", "invalid host name"),
        ("https://example.com:99999", "not a valid URL"),
        ("https://", "no host name"),
    ],
)
def test_invalid_urls(url, fragment):
    with pytest.raises(MessageValidationError) as err:
        validate_url(url)
    assert err.value.code == "invalid_url"
    assert fragment in err.value.message


def test_invalid_url_inside_message_is_reported():
    with pytest.raises(MessageValidationError) as err:
        validate_message("Try our app at https://localhost:8000 now")
    assert err.value.code == "invalid_url"
