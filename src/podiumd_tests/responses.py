"""HTTP responses: expected statuses, their messages, and the URL parts tests compare."""

from __future__ import annotations

from http import HTTPStatus
from typing import cast
from urllib.parse import urlsplit

import requests

from podiumd_tests.json_data import JsonObject
from podiumd_tests.json_data import entries

REFUSED = frozenset((HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN))
# Characters of the body an unexpected status reports: enough for an API error's detail.
BODY_EXCERPT = 300


class UnexpectedStatusError(AssertionError):
    """A response had another status than expected. An AssertionError, so pytest reports a test failure."""


def describe(response: requests.Response) -> str:
    """One line for messages: method, final URL and status."""
    # A response built without a request (unit tests, some adapters) has request None, despite the stubs.
    method = getattr(response.request, "method", None) or "GET"
    return f"{method} {response.url}: HTTP {response.status_code}"


def expect_status(response: requests.Response, *expected: int) -> requests.Response:
    """Return the response, when its status is one of expected; UnexpectedStatusError otherwise."""
    if response.status_code not in expected:
        msg = f"{describe(response)}, expected {' or '.join(str(status) for status in expected)}"
        body = " ".join(response.text.split())[:BODY_EXCERPT]
        raise UnexpectedStatusError(f"{msg}: {body}" if body else msg)
    return response


def is_server_error(response: requests.Response) -> bool:
    """Return True for a 5xx status: the component (or its ingress) is broken, whatever the client sent."""
    return response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR


def get_root(session: requests.Session, base_url: str, timeout: float | tuple[float, float]) -> requests.Response:
    """GET the root of a component, following redirects (R14: only the final answer counts)."""
    return session.get(f"{base_url}/", timeout=timeout)


def root_problem(session: requests.Session, base_url: str, timeout: float) -> str | None:
    """Return why the component's root fails ("HTTP 503", "ConnectTimeout"); None when it answers without a 5xx."""
    try:
        response = get_root(session, base_url, timeout)
    except requests.RequestException as exc:
        return type(exc).__name__
    return f"HTTP {response.status_code}" if is_server_error(response) else None


def is_root_answering(session: requests.Session, base_url: str, timeout: float) -> bool:
    """Whether the component's root answers without a server error (a refused connection counts as no)."""
    return root_problem(session, base_url, timeout) is None


def url_host(url: str) -> str:
    """Return the hostname of a URL, or "" when it has none."""
    return urlsplit(url).hostname or ""


def get_entries(http: requests.Session, url: str) -> list[JsonObject]:
    """Return the objects GET url answers with 200: a JSON array, or one under results or items (PABC)."""
    body: object = expect_status(http.get(url), HTTPStatus.OK).json()
    if isinstance(body, dict):
        found = cast("JsonObject", body)
        return entries(found.get("results") or found.get("items"))
    return entries(body)


def _invalid_params(response: requests.Response) -> list[JsonObject]:
    """Return a validation error's invalidParams; Open Object names them invalid_params."""
    body = cast("JsonObject", response.json())
    return entries(body["invalidParams"] if "invalidParams" in body else body["invalid_params"])


def invalid_codes(response: requests.Response) -> list[str]:
    """Return the codes in a ZGW validation error's invalidParams, in order."""
    return [str(param["code"]) for param in _invalid_params(response)]


def invalid_names(response: requests.Response) -> set[str]:
    """Return the field names in a ZGW validation error's invalidParams."""
    return {str(param["name"]) for param in _invalid_params(response)}
