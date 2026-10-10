"""KISS without a login: the OIDC challenge, and what anonymous users get (health: smoke test_api_health).

Ported from TA regression 100 and 147. The logged-in tests (12, 119, 190) need a KCC user
session: phase 5.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.oidc import AUTH_PATH
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import describe
from podiumd_tests.responses import is_server_error
from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    import requests

pytestmark = [pytest.mark.component, pytest.mark.requires("kiss")]


def test_challenge_redirects_to_keycloak(http: requests.Session, urls: dict[str, str]) -> None:
    """The login challenge redirects to the Keycloak auth endpoint (TA reg-100)."""
    response = http.get(urls["kiss"] + "/api/challenge", params={"returnUrl": "/"}, allow_redirects=False)
    assert response.is_redirect, describe(response)
    location = response.headers["Location"]
    assert url_host(location) == url_host(urls["keycloak"])
    assert AUTH_PATH.match(location.split(url_host(location), 1)[1].split("?")[0])


@pytest.mark.parametrize("path", ["/api/me", "/contactmomenten", "/contactverzoeken"])
def test_pages_without_login(http: requests.Session, urls: dict[str, str], path: str) -> None:
    """Anonymous /api/me and the SPA routes give no server error (TA reg-100)."""
    response = http.get(urls["kiss"] + path)
    assert not is_server_error(response), describe(response)


@pytest.mark.parametrize(("method", "path"), [("GET", "/api/search/sources"), ("POST", "/api/search")])
def test_search_needs_a_login(http: requests.Session, urls: dict[str, str], method: str, path: str) -> None:
    """KISS's search answers no anonymous call: it is refused or sent to the Keycloak login (TA reg-147)."""
    body = {"query": "a", "page": 1, "filters": []} if method == "POST" else None
    response = http.request(method, urls["kiss"] + path, json=body, allow_redirects=False)
    if response.is_redirect:
        assert url_host(response.headers["Location"]) == url_host(urls["keycloak"])
    else:
        assert response.status_code in REFUSED, describe(response)
