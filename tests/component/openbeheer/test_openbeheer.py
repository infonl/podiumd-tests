"""Open Beheer: catalogi management on top of Open Zaak's Catalogi API, for logged-in beheerders."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_ZAAKTYPE
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.json_data import entries
from podiumd_tests.openbeheer import openbeheer_session
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

pytestmark = [pytest.mark.component, pytest.mark.requires("openbeheer", "keycloak")]


@pytest.fixture(scope="module", name="openbeheer")
def fixture_openbeheer(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> requests.Session:
    """Open Beheer's API as the test admin."""
    need_bootstrap(ADMIN.name)
    return openbeheer_session(podiumd_env, ADMIN.username, podiumd_env.credentials.get(ADMIN.store_key))


def test_api_needs_a_login(http: requests.Session, urls: dict[str, str]) -> None:
    """Without a session the API refuses to say who is logged in."""
    response = http.get(urls["openbeheer"] + "/api/v1/whoami/")
    assert response.status_code in REFUSED, describe(response)


def test_keycloak_login_is_the_admin(openbeheer: requests.Session, urls: dict[str, str]) -> None:
    """After the Keycloak login Open Beheer knows the user by its Keycloak username."""
    whoami = expect_status(openbeheer.get(urls["openbeheer"] + "/api/v1/whoami/"), HTTPStatus.OK).json()
    assert whoami["username"] == ADMIN.username


@pytest.mark.requires("openzaak")
def test_open_zaaks_zaaktypen_are_managed(
    openbeheer: requests.Session, urls: dict[str, str], test_zaaktype: JsonObject
) -> None:
    """Through its Catalogi service Open Beheer lists the test catalogus and its zaaktype."""
    api = urls["openbeheer"] + "/api/v1/service"
    services = expect_status(openbeheer.get(api + "/choices/"), HTTPStatus.OK).json()
    slug = next(str(s["value"]) for s in entries(services) if "Catalogi" in str(s["label"]))
    catalogi = expect_status(openbeheer.get(f"{api}/{slug}/catalogi/choices/"), HTTPStatus.OK).json()
    assert test_zaaktype["catalogus"] in {c["value"] for c in entries(catalogi)}
    # Its zaaktypen list filters on identificatie only.
    query = {"identificatie": TEST_ZAAKTYPE}
    found = expect_status(openbeheer.get(f"{api}/{slug}/zaaktypen/", params=query), HTTPStatus.OK).json()
    assert TEST_ZAAKTYPE in {z.get("identificatie") for z in entries(found.get("results"))}, list(found)
