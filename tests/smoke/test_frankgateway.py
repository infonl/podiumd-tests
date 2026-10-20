"""Does the Frank!Gateway outway route the base registrations? Ported from TA smoke 192.

The outway has no ingress on the estates: the profile gives its in-cluster
Service URL, reached through a port-forward.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.gateway import is_no_route
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

pytestmark = [pytest.mark.smoke, pytest.mark.requires("frankgateway")]

ROUTES = {
    "brp": "/haalcentraal/api/brp/personen",
    "bag": "/lvbag/individuelebevragingen/v2/adressen",
    "kvk-basisprofiel": "/api/v1/basisprofielen/68750110",
    "kvk-vestiging": "/api/v1/vestigingsprofielen/000037178598",
    "kvk-zoeken": "/api/v2/zoeken?naam=test",
}


@pytest.mark.parametrize("path", [pytest.param(p, id=n) for n, p in ROUTES.items()])
def test_outway_routes_to_upstream(http: requests.Session, urls: dict[str, str], path: str) -> None:
    """The outway has a route, and its upstream is available (no 503).

    The BRP route only allows POST, so a GET gives 405 from the upstream.
    """
    response = http.get(urls["frankgateway"] + path, headers={"Accept": "application/json"})
    assert not is_no_route(response), f"no route for {path}"
    assert response.status_code != HTTPStatus.SERVICE_UNAVAILABLE, f"{path}: upstream unavailable"
    if path == ROUTES["brp"]:
        expect_status(response, HTTPStatus.METHOD_NOT_ALLOWED)


def test_outway_key_is_accepted_by_the_kvk_upstream(http: requests.Session, urls: dict[str, str]) -> None:
    """The KvK basisprofiel route answers 200 with the kvkNummer: the outway's API key (OpenBao) is accepted.

    A missing or wrong key would get 401/403 from KvK, not the profile; on minikube the KvK mock answers.
    """
    response = http.get(urls["frankgateway"] + ROUTES["kvk-basisprofiel"], headers={"Accept": "application/json"})
    body = expect_status(response, HTTPStatus.OK).json()
    assert str(body.get("kvkNummer")) == "68750110", f"no basisprofiel in the answer: {body}"
