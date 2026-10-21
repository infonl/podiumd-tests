"""Open Beheer: catalogi management on top of Open Zaak's Catalogi API, for logged-in beheerders."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_ZAAKTYPE
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.openbeheer import openbeheer_session
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openbeheer", "keycloak")]


@pytest.fixture(scope="module", name="openbeheer")
def fixture_openbeheer(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> requests.Session:
    """Open Beheer's API as the test admin."""
    need_bootstrap(ADMIN.name)
    return openbeheer_session(podiumd_env, ADMIN.username, podiumd_env.credentials.get(ADMIN.store_key))


@pytest.mark.source(
    "podiumd-tests",
    "Covers Open Beheer: it refuses anonymous API calls, knows the Keycloak user and manages Open Zaak's catalogi.",
)
def test_api_needs_a_login(http: requests.Session, urls: dict[str, str]) -> None:
    """Without a session the API refuses to say who is logged in."""
    response = http.get(urls["openbeheer"] + "/api/v1/whoami/")
    assert response.status_code in REFUSED, describe(response)


@pytest.mark.source(
    "podiumd-tests",
    "Covers Open Beheer: it refuses anonymous API calls, knows the Keycloak user and manages Open Zaak's catalogi.",
)
def test_keycloak_login_is_the_admin(openbeheer: requests.Session, urls: dict[str, str]) -> None:
    """After the Keycloak login Open Beheer knows the user by its Keycloak username."""
    whoami = expect_status(openbeheer.get(urls["openbeheer"] + "/api/v1/whoami/"), HTTPStatus.OK).json()
    assert whoami["username"] == ADMIN.username


@pytest.fixture(scope="module", name="catalogi_service")
def fixture_catalogi_service(openbeheer: requests.Session, urls: dict[str, str]) -> str:
    """URL of Open Beheer's Catalogi service API."""
    api = urls["openbeheer"] + "/api/v1/service"
    services = expect_status(openbeheer.get(api + "/choices/"), HTTPStatus.OK).json()
    return f"{api}/{next(str(s['value']) for s in entries(services) if 'Catalogi' in str(s['label']))}"


def zaaktype_ids(openbeheer: requests.Session, catalogi_service: str, **query: str) -> set[object]:
    """The identificaties in the first page of the service's zaaktypen list for this query."""
    found = expect_status(openbeheer.get(f"{catalogi_service}/zaaktypen/", params=query), HTTPStatus.OK).json()
    return {z.get("identificatie") for z in entries(found.get("results"))}


@pytest.mark.requires("openzaak")
@pytest.mark.source(
    "podiumd-tests",
    "Covers Open Beheer: it refuses anonymous API calls, knows the Keycloak user and manages Open Zaak's catalogi.",
)
def test_open_zaaks_zaaktypen_are_managed(
    openbeheer: requests.Session, catalogi_service: str, test_zaaktype: JsonObject
) -> None:
    """Through its Catalogi service Open Beheer lists the test catalogus and its zaaktype."""
    catalogi = expect_status(openbeheer.get(f"{catalogi_service}/catalogi/choices/"), HTTPStatus.OK).json()
    assert test_zaaktype["catalogus"] in {c["value"] for c in entries(catalogi)}
    assert TEST_ZAAKTYPE in zaaktype_ids(openbeheer, catalogi_service, identificatie=TEST_ZAAKTYPE)


@pytest.mark.requires("openzaak")
@pytest.mark.xfail(
    strict=True,
    reason="[open-beheer-2] Open Beheer 0.9.1: the zaaktypen filter catalogus takes the catalogus UUID while"
    " catalogi/choices offers its URL, so the list is empty; not yet reported upstream",
)
@pytest.mark.source(
    "podiumd-tests",
    "Pins Open Beheer's known defect: a catalogus from catalogi/choices filters the zaaktypen to nothing.",
)
def test_zaaktypen_filter_on_a_catalogus_from_its_choices(
    openbeheer: requests.Session, catalogi_service: str, test_zaaktype: JsonObject
) -> None:
    """A catalogus value from catalogi/choices filters the zaaktypen list to that catalogus's zaaktypen."""
    query = {"catalogus": str(test_zaaktype["catalogus"]), "identificatie": TEST_ZAAKTYPE}
    assert TEST_ZAAKTYPE in zaaktype_ids(openbeheer, catalogi_service, **query)


@pytest.mark.requires("openzaak")
@pytest.mark.source(
    "upstream maykinmedia/open-beheer backend/src/openbeheer/zaaktype/tests/e2e/test_22_create_zaaktype.py",
    "A beheerder creates a zaaktype from the Basis template with an identificatie and omschrijving.",
)
@pytest.mark.source(
    "upstream maykinmedia/open-beheer backend/src/openbeheer/zaaktype/tests/e2e/test_24_edit_zaaktype.py",
    "A beheerder edits a zaaktype's fields.",
)
def test_beheerder_creates_and_changes_a_concept_zaaktype_from_the_template(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    openbeheer: requests.Session,
    urls: dict[str, str],
    catalogi_service: str,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    test_zaaktype: JsonObject,
) -> None:
    """From the Basis template Open Beheer makes a concept zaaktype in Open Zaak, and a change reaches Open Zaak too.

    The template leaves omschrijvingGeneriek empty, which the beheerder fills in (Open Zaak requires it).
    """
    templates = expect_status(openbeheer.get(urls["openbeheer"] + "/api/v1/template/zaaktype/"), HTTPStatus.OK)
    basis = next(t for t in entries(templates.json().get("results")) if t.get("naam") == "Basis")
    naam = registry.tagged("zaaktype")
    body = {
        **{k: v for k, v in section(basis, "waarden").items() if k != "_expand"},
        "catalogus": test_zaaktype["catalogus"],
        "identificatie": naam,
        "omschrijving": naam,
        "omschrijvingGeneriek": "podiumd-tests",
    }
    created = expect_status(openbeheer.post(f"{catalogi_service}/zaaktypen/", json=body), HTTPStatus.CREATED).json()
    url = str(created["url"])
    registry.add(f"concept zaaktype {naam}", lambda: openzaak.delete(url))
    assert (openzaak.get(url)["omschrijving"], openzaak.get(url)["concept"]) == (naam, True)
    changed = f"{naam}-gewijzigd"
    patch = openbeheer.patch(f"{catalogi_service}/zaaktypen/{created['uuid']}/", json={"omschrijving": changed})
    expect_status(patch, HTTPStatus.OK)
    assert openzaak.get(url)["omschrijving"] == changed
