"""ITA as the klantcontactmedewerker: what the detail page of a contactverzoek shows about the klant.

The contactverzoeken are assigned to the KCC user's groep (ITA_GROEP), so the user may open them.
"""

from __future__ import annotations

import json

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ITA_GROEP
from podiumd_tests.kcc import expect_ita_group_access_bug
from podiumd_tests.kcc import ita_detail_text
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.objecten import clean_up_logboek
from podiumd_tests.seed.openklant import make_actor
from podiumd_tests.seed.openklant import make_betrokkene
from podiumd_tests.seed.openklant import make_digitaal_adres
from podiumd_tests.seed.openklant import make_internetaak
from podiumd_tests.seed.openklant import make_klantcontact
from podiumd_tests.seed.openklant import make_partij
from podiumd_tests.seed.openklant import make_partij_identificator
from podiumd_tests.seed.openklant import random_bsn

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.requires("ita", "openklant", "keycloak")]

ITA_E2E = "upstream interne-taak-afhandeling/ITA InterneTaakAfhandeling.EndToEndTest/Contactverzoek"
# The adressen of the betrokkene and of its partij per case; None: no partij.
ADRES_CASES = {
    "partij-adres-when-betrokkene-has-none": ([], ["partij"]),
    "betrokkene-adres-wins": (["betrokkene"], ["partij"]),
    "none-without-partij": ([], None),
    "none-when-partij-has-none": ([], []),
}


@pytest.fixture(name="contactverzoek")
def fixture_contactverzoek(
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    logboek_type: str,
    need_bootstrap: Callable[..., None],
    request: pytest.FixtureRequest,
    podiumd_env: Environment,
) -> Callable[[JsonObject], JsonObject]:
    """Return a factory: an internetaak for ITA_GROEP raised by the klantcontact."""
    expect_ita_group_access_bug(request, podiumd_env)
    need_bootstrap("objecten-medewerker-kcc")
    groep = make_actor(openklant, registry, "organisatorische_eenheid", ITA_GROEP, "grp")

    def create(klantcontact: JsonObject) -> JsonObject:
        taak = make_internetaak(openklant, registry, klantcontact, [groep])
        clean_up_logboek(objecten, registry, logboek_type, str(taak["uuid"]))
        return taak

    return create


@pytest.mark.parametrize("case", list(ADRES_CASES))
@pytest.mark.source(
    f"{ITA_E2E}/DigitaleAdressenFallbackScenarios.cs",
    "The partij's addresses show when the betrokkene has none; the betrokkene's own win; empty without either.",
)
@pytest.mark.scenario("""
    Given a contactverzoek of a klant, with or without e-mail addresses of their own and of their partij
    When the KCC medewerker opens it in ITA
    Then the detail shows the klant's own e-mail address, else the partij's, else none
""")
def test_detail_falls_back_to_the_partijs_adressen(
    ita: requests.Session,
    urls: dict[str, str],
    openklant: ApiClient,
    registry: ResourceRegistry,
    contactverzoek: Callable[[JsonObject], JsonObject],
    case: str,
) -> None:
    """InterneTaakDetails' email: the betrokkene's digitale adressen, else its partij's (ITA's fallback)."""
    own, of_partij = ADRES_CASES[case]
    partij = None if of_partij is None else make_partij(openklant, registry)
    for name in of_partij or []:
        make_digitaal_adres(openklant, registry, partij, f"{registry.tagged(name)}@example.invalid")
    klantcontact = make_klantcontact(openklant, registry)
    betrokkene = make_betrokkene(openklant, registry, klantcontact, partij)
    for name in own:
        make_digitaal_adres(openklant, registry, None, f"{registry.tagged(name)}@example.invalid", betrokkene)
    shown = (own or of_partij or [None])[0]
    detail = json.loads(ita_detail_text(ita, urls["ita"], contactverzoek(klantcontact)))
    expected = f"{registry.tagged(shown)}@example.invalid" if shown else None
    assert detail.get("email") == expected


@pytest.mark.source(
    f"{ITA_E2E}/ContactverzoekScenarios.cs",
    "The detail names the klant of a contactverzoek for a person known by BSN.",
)
@pytest.mark.scenario("""
    Given a contactverzoek of a person known in Open Klant by BSN
    When the KCC medewerker opens it in ITA
    Then the detail shows the klant's name
""")
def test_detail_names_the_klant_of_a_bsn_partij(
    ita: requests.Session,
    urls: dict[str, str],
    openklant: ApiClient,
    registry: ResourceRegistry,
    contactverzoek: Callable[[JsonObject], JsonObject],
) -> None:
    """InterneTaakDetails' klantNaam is the betrokkene's volledigeNaam."""
    partij = make_partij(openklant, registry)
    make_partij_identificator(openklant, registry, partij, "bsn", random_bsn())
    klantcontact = make_klantcontact(openklant, registry)
    betrokkene = make_betrokkene(openklant, registry, klantcontact, partij)
    detail = json.loads(ita_detail_text(ita, urls["ita"], contactverzoek(klantcontact)))
    assert detail.get("klantNaam") == openklant.get(str(betrokkene["url"])).get("volledigeNaam")
    assert detail.get("klantNaam")


@pytest.mark.source(
    f"{ITA_E2E}/KlantcontactZoekenScenarios.cs",
    "A klantcontactnummer that led to several contactverzoeken gives the generic error.",
)
@pytest.mark.scenario("""
    Given a klantcontact that led to two contactverzoeken
    When the KCC medewerker searches a contactverzoek by that klantcontact's nummer
    Then ITA answers that it cannot choose
""")
def test_klantcontactnummer_of_two_contactverzoeken_is_refused(
    ita: requests.Session,
    urls: dict[str, str],
    openklant: ApiClient,
    registry: ResourceRegistry,
    contactverzoek: Callable[[JsonObject], JsonObject],
) -> None:
    """GET /api/internetaken/by-klantcontact/{nummer} answers 409 when the klantcontact has two internetaken."""
    klantcontact = make_klantcontact(openklant, registry)
    for _ in range(2):
        contactverzoek(klantcontact)
    found = ita.get(f"{urls['ita']}/api/internetaken/by-klantcontact/{klantcontact['nummer']}")
    expect_status(found, HTTPStatus.CONFLICT)
