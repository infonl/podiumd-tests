"""KISS without a login: health, the OIDC challenge, and what anonymous users get.

Ported from TA regression 100 and 147. The logged-in tests (12, 119, 190) need a KCC user
session: phase 5.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.oidc import AUTH_PATH
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import is_server_error
from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    import requests

pytestmark = [pytest.mark.component, pytest.mark.requires("kiss")]

INDEXES = ("kennisbank", "vraagantwoord", "website")


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


@pytest.mark.parametrize("index", INDEXES)
def test_search_indexes_are_not_open(http: requests.Session, urls: dict[str, str], index: str) -> None:
    """An anonymous Elasticsearch query through KISS is refused or answers, never a server error (TA reg-147)."""
    body = {"query": {"match_all": {}}, "size": 1}
    response = http.post(f"{urls['kiss']}/api/elasticsearch/{index}/_search", json=body)
    assert response.status_code in {HTTPStatus.OK, HTTPStatus.NOT_FOUND, *REFUSED}, describe(response)


def test_healthcheck(http: requests.Session, urls: dict[str, str]) -> None:
    """KISS's own health check answers 200 (TA reg-100, 147)."""
    expect_status(http.get(urls["kiss"] + "/api/healthcheck"), HTTPStatus.OK)
