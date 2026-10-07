"""PABC decision endpoint with the API key: unknown or no functional roles give no application roles.

Ported from TA regression 68b and 68c; 68a, which needs a PABC session, is in test_management.py.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.pabc import decide
from podiumd_tests.responses import describe

if TYPE_CHECKING:
    import requests

pytestmark = [pytest.mark.component, pytest.mark.requires("pabc")]


def test_unknown_functional_role_gets_no_application_roles(
    http: requests.Session, urls: dict[str, str], pabc_api_key: str
) -> None:
    """A role name PABC does not know maps to no application roles (TA reg-68c)."""
    response = decide(http, urls["pabc"], pabc_api_key, ["ptest-onbekende-rol"])
    assert response.status_code == HTTPStatus.OK, describe(response)
    assert all(not entries(r.get("applicationRoles")) for r in entries(response.json()["results"]))


def test_no_functional_roles(http: requests.Session, urls: dict[str, str], pabc_api_key: str) -> None:
    """No role names: no application roles, or a validation error (TA reg-68b)."""
    response = decide(http, urls["pabc"], pabc_api_key, [])
    if response.status_code == HTTPStatus.OK:
        assert all(not entries(r.get("applicationRoles")) for r in entries(response.json()["results"]))
    else:
        assert response.status_code in {HTTPStatus.BAD_REQUEST, HTTPStatus.UNPROCESSABLE_ENTITY}, describe(response)
