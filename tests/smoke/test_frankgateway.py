"""Does the Frank!Gateway outway route the base registrations? Ported from TA smoke 192.

The outway is often only reachable in the cluster; then the profile has no
frankgateway URL and these tests skip. "No route" is APISIX's 404 with an
error_msg about the route: the request did not reach any upstream.
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import requests

pytestmark = [pytest.mark.smoke, pytest.mark.requires("frankgateway")]

ROUTES = {
    "brp": "/haalcentraal/api/brp/ingeschrevenpersonen",
    "bag": "/lvbag/individuelebevragingen/v2/adressen",
    "kvk-basisprofiel": "/api/v1/basisprofielen/68750110",
    "kvk-vestiging": "/api/v1/vestigingsprofielen/000037171195",
    "kvk-zoeken": "/api/v2/zoeken?naam=test",
}


def _no_route(response: requests.Response) -> bool:
    if response.status_code != 404:
        return False
    try:
        message: object = response.json().get("error_msg")
    except ValueError:
        return False
    return isinstance(message, str) and re.search("route", message, re.IGNORECASE) is not None


@pytest.mark.parametrize("path", [pytest.param(p, id=n) for n, p in ROUTES.items()])
def test_outway_routes_to_upstream(http: requests.Session, urls: dict[str, str], path: str) -> None:
    """The outway has a route, and its upstream is available (no 503).

    The BRP route only allows POST, so a GET gives 405 from the upstream.
    """
    response = http.get(urls["frankgateway"] + path, headers={"Accept": "application/json"})
    assert not _no_route(response), f"no route for {path}"
    assert response.status_code != 503, f"{path}: upstream unavailable"
    if path == ROUTES["brp"]:
        assert response.status_code == 405, f"{path}: HTTP {response.status_code}"
