"""KISS as the klantcontactmedewerker: a session with the KCC role, and klantcontacten through KISS.

Ported from TA smoke 113 and regression 12.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.kcc import KISS_KLANTCONTACTEN
from podiumd_tests.kcc import kcc_login
from podiumd_tests.kcc import kiss_register
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openklant import klantcontact_body

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.core, pytest.mark.requires("kiss", "keycloak")]


@pytest.fixture(name="kiss")
def fixture_kiss(page: Page, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> requests.Session:
    """KISS in the KCC test user's session."""
    need_bootstrap(KCC.name)
    return kcc_login(page, podiumd_env, "kiss")


def test_kcc_user_is_a_klantcontactmedewerker(kiss: requests.Session, urls: dict[str, str]) -> None:
    """KISS knows the logged-in user as a klantcontactmedewerker (TA smoke 113)."""
    me = expect_status(kiss.get(urls["kiss"] + "/api/me"), HTTPStatus.OK).json()
    assert me["isLoggedIn"]
    assert me["isKcm"]


def test_klantcontact_through_kiss(
    kiss: requests.Session, urls: dict[str, str], openklant: ApiClient, registry: ResourceRegistry
) -> None:
    """A klantcontact registered through KISS lands in Open Klant (TA reg-12).

    KISS does not delete klantcontacten (DELETE answers 405); cleanup goes to Open Klant.
    """
    body = klantcontact_body(registry, onderwerp=registry.tagged("kiss-klantcontact"))
    response = kiss.post(urls["kiss"] + KISS_KLANTCONTACTEN, json=body, headers=kiss_register(kiss, urls["kiss"]))
    created = expect_status(response, HTTPStatus.CREATED).json()
    registry.add(f"klantcontact {created['url']}", lambda: openklant.delete(str(created["url"])))
    assert openklant.get(f"klantcontacten/{created['uuid']}")["onderwerp"] == body["onderwerp"]
