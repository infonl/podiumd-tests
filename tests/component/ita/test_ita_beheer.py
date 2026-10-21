"""ITA's functioneel beheerder: Alle contactverzoeken, and reopening a closed contactverzoek.

Ported from ITA's own Playwright suite (InterneTaakAfhandeling.EndToEndTest), as the API calls of its pages.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ITA_BEHEERDER
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.kcc import kcc_login
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.objecten import clean_up_logboek
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openklant import make_internetaak
from podiumd_tests.seed.openklant import make_klantcontact

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.bootstrap.keycloak import KeycloakUser
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.requires("ita", "openklant", "objecten", "keycloak")]

E2E = "upstream interne-taak-afhandeling/ITA InterneTaakAfhandeling.EndToEndTest"


@pytest.fixture(name="closed_taak")
def fixture_closed_taak(
    podiumd_env: Environment, openklant: ApiClient, objecten: ApiClient, registry: ResourceRegistry
) -> JsonObject:
    """An internetaak raised by a klantcontact and set to verwerkt; ITA's logboek of it is cleaned up too."""
    taak = make_internetaak(openklant, registry, make_klantcontact(openklant, registry), [])
    clean_up_logboek(objecten, registry, objecttype_url(podiumd_env, "Activiteitenlog"), str(taak["uuid"]))
    return openklant.patch(str(taak["url"]), {"status": "verwerkt"})


@pytest.fixture(name="ita_as")
def fixture_ita_as(
    page: Page, podiumd_env: Environment, need_bootstrap: Callable[..., None]
) -> Callable[[KeycloakUser], requests.Session]:
    """An ITA session of a test user, logged in in the browser; each login replaces the browser's previous one."""

    def login(user: KeycloakUser) -> requests.Session:
        need_bootstrap(user.name)
        page.context.clear_cookies()
        return kcc_login(page, podiumd_env, "ita", user)

    return login


@pytest.mark.source(
    f"{E2E}/AlleContactverzoeken/AlleContactverzoekenAccessScenarios.cs",
    "A beheerder opens Alle contactverzoeken; a medewerker without the beheerder role is blocked.",
)
def test_only_the_beheerder_lists_all_contactverzoeken(
    ita_as: Callable[[KeycloakUser], requests.Session], urls: dict[str, str]
) -> None:
    """ITA's list of all internetaken answers the functioneel beheerder and refuses the KCC user."""
    alle = urls["ita"] + "/api/internetaken"
    expect_status(ita_as(ITA_BEHEERDER).get(alle), HTTPStatus.OK)
    expect_status(ita_as(KCC).get(alle), *REFUSED)


@pytest.mark.source(
    f"{E2E}/Contactverzoek/HeropenContactverzoekScenarios.cs",
    "A beheerder reopens a closed contactverzoek with a reason; confirming without a reason is not possible.",
)
def test_beheerder_reopens_a_closed_contactverzoek(
    ita_as: Callable[[KeycloakUser], requests.Session],
    urls: dict[str, str],
    openklant: ApiClient,
    closed_taak: JsonObject,
) -> None:
    """Without a reason the reopen is refused; with one the internetaak is open again and the KCC may not reopen."""
    heropen = f"{urls['ita']}/api/internetaken/{closed_taak['uuid']}/heropen"
    beheerder = ita_as(ITA_BEHEERDER)
    expect_status(beheerder.post(heropen, json={"reden": ""}), HTTPStatus.BAD_REQUEST)
    expect_status(ita_as(KCC).post(heropen, json={"reden": "podiumd-tests"}), *REFUSED)
    expect_status(beheerder.post(heropen, json={"reden": "podiumd-tests"}), HTTPStatus.OK)
    assert openklant.get(f"internetaken/{closed_taak['uuid']}")["status"] == "te_verwerken"
