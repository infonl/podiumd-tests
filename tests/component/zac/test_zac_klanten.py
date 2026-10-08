"""ZAC looks up a person in the BRP and a company in KvK through its own REST API.

Ported from TA regression 193. No estate routes ZAC to Open Zaak through Frank!Gateway; rollen
with these identities in Open Zaak are covered by tests/component/openzaak/test_statussen_rollen.py.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import KVK_TEST_NUMMER
from podiumd_tests.bootstrap.steps import KeycloakUser
from podiumd_tests.browser import redirect_login
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.requires("zac", "keycloak")]

ADMIN = KeycloakUser("admin")
EREBOS = "999990019"


@pytest.fixture(name="zac")
def fixture_zac(page: Page, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> requests.Session:
    """The test admin's ZAC session."""
    need_bootstrap(ADMIN.name)
    urls = podiumd_env.profile.urls
    return redirect_login(page, podiumd_env, urls["zac"], ADMIN.username, podiumd_env.credentials.get(ADMIN.store_key))


def test_person_lookup(zac: requests.Session, urls: dict[str, str]) -> None:
    """ZAC finds a BRP test-set person by BSN, with the name (TA reg-193)."""
    found = expect_status(zac.put(urls["zac"] + "/rest/klanten/personen", json={"bsn": EREBOS}), HTTPStatus.OK)
    personen = found.json()["resultaten"]
    assert [p["bsn"] for p in personen] == [EREBOS]
    assert "Bultenaar" in personen[0]["naam"]


def test_company_lookup(zac: requests.Session, urls: dict[str, str]) -> None:
    """ZAC finds the KvK test company's basisprofiel by KvK number (TA reg-193)."""
    url = f"{urls['zac']}/rest/klanten/basisprofiel/{KVK_TEST_NUMMER}"
    bedrijf = expect_status(zac.get(url), HTTPStatus.OK).json()
    assert bedrijf["kvkNummer"] == KVK_TEST_NUMMER
    assert "Test BV Donald" in str(bedrijf.get("statutaireNaam") or bedrijf.get("eersteHandelsnaam"))
