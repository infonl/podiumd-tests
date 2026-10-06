"""HTTP responses: expected statuses, their messages, and the URL parts tests compare."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    import requests

REFUSED = frozenset({HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN})


class UnexpectedStatusError(AssertionError):
    """A response had another status than expected. An AssertionError, so pytest reports a test failure."""


def describe(response: requests.Response) -> str:
    """One line for messages: method, final URL and status."""
    # A response built without a request (unit tests, some adapters) has request None, despite the stubs.
    method = getattr(response.request, "method", None) or "GET"
    return f"{method} {response.url}: HTTP {response.status_code}"


def expect_status(response: requests.Response, *expected: int) -> requests.Response:
    """The response, when its status is one of expected; UnexpectedStatusError otherwise."""
    if response.status_code not in expected:
        msg = f"{describe(response)}, expected {' or '.join(str(e) for e in expected)}"
        raise UnexpectedStatusError(msg)
    return response


def is_server_error(response: requests.Response) -> bool:
    """True for a 5xx status: the component (or its ingress) is broken, whatever the client sent."""
    return response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR


def get_root(session: requests.Session, base_url: str, timeout: float | tuple[float, float]) -> requests.Response:
    """GET the root of a component, following redirects (R14: only the final answer counts)."""
    return session.get(base_url + "/", timeout=timeout)


def url_host(url: str) -> str:
    """The hostname of a URL, or "" when it has none."""
    return urlsplit(url).hostname or ""
