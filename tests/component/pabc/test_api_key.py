"""PABC decision endpoint with the API key: unknown or no functional roles give no application roles.

Ported from TA regression 68b and 68c. The cookie-session tests (67, 68a, 69, 71) need a
logged-in user over HTTPS: phase 5.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.responses import describe

if TYPE_CHECKING:
    import requests

    from podiumd_tests.credentials import SecretResolver

pytestmark = [pytest.mark.component, pytest.mark.requires("pabc")]

PATH = "/api/v1/application-roles-per-entity-type"


@pytest.fixture(name="api_key")
def fixture_api_key(credentials: SecretResolver) -> str:
    """PABC's API key (secret pabc_api_key); skip when the profile has none."""
    key = credentials.optional("pabc_api_key")
    if not key:
        pytest.skip("no secret pabc_api_key in the profile")
    return key


def roles(http: requests.Session, urls: dict[str, str], api_key: str, names: list[str]) -> requests.Response:
    """POST the decision endpoint for functional role names."""
    return http.post(urls["pabc"] + PATH, json={"FunctionalRoleNames": names}, headers={"X-API-KEY": api_key})


def test_unknown_functional_role_gets_no_application_roles(
    http: requests.Session, urls: dict[str, str], api_key: str
) -> None:
    """A role name PABC does not know maps to no application roles (TA reg-68c)."""
    response = roles(http, urls, api_key, ["ptest-onbekende-rol"])
    assert response.status_code == HTTPStatus.OK, describe(response)
    assert all(not entries(r.get("applicationRoles")) for r in entries(response.json()["results"]))


def test_no_functional_roles(http: requests.Session, urls: dict[str, str], api_key: str) -> None:
    """No role names: no application roles, or a validation error (TA reg-68b)."""
    response = roles(http, urls, api_key, [])
    if response.status_code == HTTPStatus.OK:
        assert all(not entries(r.get("applicationRoles")) for r in entries(response.json()["results"]))
    else:
        assert response.status_code in {HTTPStatus.BAD_REQUEST, HTTPStatus.UNPROCESSABLE_ENTITY}, describe(response)
