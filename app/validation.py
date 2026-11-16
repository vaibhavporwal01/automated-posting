"""Message rules: length limit, exactly one call-to-action link, and URL checks.

Kept free of FastAPI/Pydantic so the rules can be unit tested on their own and
reused by any caller.
"""

import ipaddress
import re
from typing import List
from urllib.parse import urlsplit

MAX_MESSAGE_LENGTH = 200
MAX_URL_LENGTH = 2048

# Anything with a scheme ("https://", "ftp://") or starting with "www." is treated
# as a link, so a second link cannot slip past the "exactly one" rule just
# because it lacks a scheme.
_LINK_PATTERN = re.compile(r"(?:\b[a-zA-Z][a-zA-Z0-9+.\-]*://|\bwww\.)\S+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?'\")]}>"
_HOSTNAME_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$", re.IGNORECASE)
_TLD = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})$", re.IGNORECASE)


class MessageValidationError(ValueError):
    """Raised when a message breaks one of the posting rules."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def extract_links(text: str) -> List[str]:
    """Return every link-like token in the text, with trailing punctuation removed."""
    links = []
    for match in _LINK_PATTERN.finditer(text):
        candidate = match.group(0).rstrip(_TRAILING_PUNCTUATION)
        if candidate:
            links.append(candidate)
    return links


def validate_url(url: str) -> str:
    """Check that a link is an absolute, public http(s) URL. Returns the URL unchanged."""
    if len(url) > MAX_URL_LENGTH:
        raise MessageValidationError("invalid_url", "The link is longer than 2048 characters.")

    if url.lower().startswith("www."):
        raise MessageValidationError(
            "invalid_url", f"The link '{url}' must start with http:// or https://."
        )

    try:
        parts = urlsplit(url)
        port = parts.port  # raises ValueError for a bad port
    except ValueError:
        raise MessageValidationError("invalid_url", f"The link '{url}' is not a valid URL.") from None

    if parts.scheme.lower() not in ("http", "https"):
        raise MessageValidationError(
            "invalid_url",
            f"The link '{url}' uses an unsupported scheme. Use http:// or https://.",
        )
    if parts.username or parts.password:
        raise MessageValidationError("invalid_url", "The link must not contain a username or password.")

    host = parts.hostname
    if not host:
        raise MessageValidationError("invalid_url", f"The link '{url}' has no host name.")

    if port == 0:
        raise MessageValidationError("invalid_url", f"The link '{url}' has an invalid port.")

    _validate_host(host, url)
    return url


def _validate_host(host: str, url: str) -> None:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None

    if address is not None:
        if address.is_private or address.is_loopback or address.is_link_local or address.is_unspecified:
            raise MessageValidationError(
                "invalid_url", f"The link '{url}' points to a private address and would not work for readers."
            )
        return

    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise MessageValidationError("invalid_url", f"The link '{url}' has an invalid host name.") from None

    labels = ascii_host.rstrip(".").split(".")
    if len(labels) < 2:
        raise MessageValidationError(
            "invalid_url", f"The link '{url}' needs a full domain name such as example.com."
        )
    if not all(_HOSTNAME_LABEL.match(label) for label in labels) or not _TLD.match(labels[-1]):
        raise MessageValidationError("invalid_url", f"The link '{url}' has an invalid host name.")


def validate_message(raw: str) -> str:
    """Apply every rule to a message and return the cleaned text."""
    if not isinstance(raw, str):
        raise MessageValidationError("invalid_type", "The message must be a string.")

    message = raw.strip()
    if not message:
        raise MessageValidationError("empty_message", "The message must not be empty.")

    if len(message) > MAX_MESSAGE_LENGTH:
        raise MessageValidationError(
            "message_too_long",
            f"The message must not exceed {MAX_MESSAGE_LENGTH} characters (got {len(message)}).",
        )

    links = extract_links(message)
    if not links:
        raise MessageValidationError(
            "missing_link", "The message must include exactly one call-to-action link (found none)."
        )
    if len(links) > 1:
        raise MessageValidationError(
            "multiple_links",
            f"The message must include exactly one call-to-action link (found {len(links)}).",
        )

    validate_url(links[0])
    return message
