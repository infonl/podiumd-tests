"""Chain: a contactverzoek the KCC medewerker registers in KISS is found in KISS and shows in ITA.

KISS's frontend saves it as a klantcontact, a betrokkene with the klant's phone number or e-mail address,
the actoren it is assigned to, and an internetaak (KISS's own routes and its Open Klant proxy).
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ITA_GROEP
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.json_data import entries
from podiumd_tests.kcc import expect_ita_group_access_bug
from podiumd_tests.kcc import internetaken_of
from podiumd_tests.kcc import ita_detail_text
from podiumd_tests.kcc import kcc_login
from podiumd_tests.kcc import kiss_actor
from podiumd_tests.kcc import kiss_contactverzoek
from podiumd_tests.kcc import kiss_contactverzoeken_by_adres
from podiumd_tests.kcc import kiss_klantcontacten
from podiumd_tests.kcc import kiss_medewerkers
from podiumd_tests.kcc import kiss_sync_cronjob
from podiumd_tests.mailpit import own_address
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.objecten import make_object
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openklant import make_organisatie
from podiumd_tests.seed.openklant import make_partij
from podiumd_tests.seed.openklant import random_nummer
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import run_cronjob

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

KISS_E2E = "upstream KISS-frontend Kiss.Bff.EndToEndTest"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.ui,
    pytest.mark.core,
    pytest.mark.requires("kiss", "openklant", "keycloak"),
]


@pytest.fixture(name="kiss")
def fixture_kiss(page: Page, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> requests.Session:
    """KISS in the KCC test user's session."""
    need_bootstrap(KCC.name)
    page.context.clear_cookies()
    return kcc_login(page, podiumd_env, "kiss")


@pytest.fixture(name="ita")
def fixture_ita(page: Page, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> requests.Session:
    """ITA in the KCC test user's session, a member of ITA_GROEP."""
    need_bootstrap(KCC.name, "openklant-actor-kcc", "objecten-medewerker-kcc")
    page.context.clear_cookies()
    return kcc_login(page, podiumd_env, "ita")


def _actoren_of(taak: JsonObject) -> list[str]:
    return [str(actor.get("uuid")) for actor in entries(taak.get("toegewezenAanActoren"))]


def _adres(registry: ResourceRegistry, soort: str) -> str:
    """A phone number or e-mail address no other test uses."""
    return own_address(registry) if soort == "email" else f"06{random_nummer()[-8:]}"


@pytest.mark.parametrize(
    ("actor", "adres"),
    [("afdeling", "telefoonnummer"), ("afdeling", "email"), ("groep", "telefoonnummer"), ("groep", "email")],
)
@pytest.mark.source(
    f"{KISS_E2E} AnonymousContactVerzoekScenarios",
    "A contactverzoek to an afdeling or groep, with a phone number or e-mail address, is found by that address.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to KISS
    When the medewerker registers a contactverzoek for an afdeling or groep, with the klant's phone or e-mail
    Then the contactverzoek is assigned to that afdeling or groep
    And KISS's contactverzoek search finds it by that phone number or e-mail address
""")
def test_contactverzoek_from_kiss_is_found_by_the_klants_adres(
    kiss: requests.Session,
    urls: dict[str, str],
    openklant: ApiClient,
    registry: ResourceRegistry,
    actor: str,
    adres: str,
) -> None:
    """postklantcontacten and postinternetaak with an actor; KISS's search by digitaal adres finds the internetaak."""
    eenheid = kiss_actor(kiss, urls["kiss"], openklant, registry, actor, registry.tagged(f"kiss-{actor}-{adres}"))
    klant_adres = _adres(registry, adres)
    taak = kiss_contactverzoek(kiss, urls["kiss"], openklant, registry, [eenheid], klant_adres)
    assert _actoren_of(taak) == [eenheid["uuid"]]
    assert kiss_contactverzoeken_by_adres(kiss, urls["kiss"], klant_adres) == [taak["uuid"]]


@pytest.mark.tc("ITA-035")
@pytest.mark.source(
    "draaiboek ITA-035",
    "A contactverzoek submitted through Contact shows all its recorded information on ITA's detail page.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to KISS and ITA
    When the medewerker registers a contactverzoek for their groep in KISS
    Then ITA's detail page shows its onderwerp, vraag, toelichting and the klant's name
""")
def test_contactverzoek_from_kiss_shows_in_full_in_ita(  # noqa: FNE008  # the name is the test id
    kiss: requests.Session,
    ita: requests.Session,
    urls: dict[str, str],
    openklant: ApiClient,
    registry: ResourceRegistry,
    request: pytest.FixtureRequest,
    podiumd_env: Environment,
) -> None:
    """A contactverzoek registered through KISS for ITA_GROEP shows in full in ITA."""
    expect_ita_group_access_bug(request, podiumd_env)
    groep = kiss_actor(kiss, urls["kiss"], openklant, registry, "groep", ITA_GROEP)
    taak = kiss_contactverzoek(kiss, urls["kiss"], openklant, registry, [groep], _adres(registry, "email"))
    klantcontact = openklant.get(str(taak["aanleidinggevendKlantcontact"]["url"]))  # pyright: ignore[reportIndexIssue]
    detail = ita_detail_text(ita, urls["ita"], taak)
    shown = (klantcontact["onderwerp"], klantcontact["inhoud"], taak["toelichting"], "PodiumD")
    assert [str(value) for value in shown if str(value) not in detail] == []


@pytest.mark.parametrize("soort", ["persoon", "organisatie"])
@pytest.mark.source(
    f"{KISS_E2E} AnonymousContactVerzoekPersonCompany",
    "A contactverzoek for a person or a vestiging shows on that klant's Contactverzoeken tab.",
)
@pytest.mark.scenario("""
    Given a person or an organisation known in Open Klant
    When the KCC medewerker registers a contactverzoek for that klant in KISS
    Then KISS lists the contactverzoek for that klant
""")
def test_contactverzoek_for_a_klant_is_listed_for_that_klant(
    kiss: requests.Session, urls: dict[str, str], openklant: ApiClient, registry: ResourceRegistry, soort: str
) -> None:
    """The internetaak is among those of the partij's klantcontacten, as KISS's Contactverzoeken tab reads them."""
    partij = make_partij(openklant, registry) if soort == "persoon" else make_organisatie(openklant, registry)
    afdeling = kiss_actor(
        kiss, urls["kiss"], openklant, registry, "afdeling", registry.tagged(f"kiss-afdeling-{soort}")
    )
    adres = _adres(registry, "telefoonnummer")
    taak = kiss_contactverzoek(kiss, urls["kiss"], openklant, registry, [afdeling], adres, partij)
    listed = kiss_klantcontacten(
        kiss, urls["kiss"], hadBetrokkene__wasPartij__url=str(partij["url"]), expand="leiddeTotInterneTaken"
    )
    assert internetaken_of(listed) == [taak["uuid"]]


@pytest.mark.requires("kiss", "openklant", "keycloak", "objecten", "ita", "cluster")
@pytest.mark.xdist_group("kiss-sync")  # the sync rewrites the whole index
@pytest.mark.source(
    f"{KISS_E2E} AnonymousContactVerzoekScenarios",
    "A contactverzoek to a medewerker picked from the smoelenboek within an afdeling or groep is assigned to both.",
)
@pytest.mark.scenario("""
    Given a medewerker of an afdeling and of the KCC medewerker's groep in the smoelenboek
    When the KCC medewerker finds that medewerker within the afdeling and within the groep in KISS
    And registers a contactverzoek for the medewerker and the groep
    Then the contactverzoek is assigned to the medewerker and the groep
    And ITA shows it to the KCC medewerker, a member of the groep
""")
def test_contactverzoek_to_a_medewerker_from_the_smoelenboek(
    kiss: requests.Session,
    ita: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    request: pytest.FixtureRequest,
) -> None:
    """KISS's medewerker search finds a smoelenboek entry by afdeling and groep; the internetaak goes to it and ITA_GROEP."""
    found = expect_status(kiss.get(f"{urls['kiss']}/api/environment/use-medewerkeremail"), HTTPStatus.OK).json()
    if found.get("useMedewerkeremail"):
        pytest.skip("KISS takes a medewerker's e-mail address instead of the smoelenboek (USE_MEDEWERKEREMAIL)")
    expect_ita_group_access_bug(request, podiumd_env)
    identificatie = registry.tagged("medewerker")
    afdeling = registry.tagged("afdeling")
    cronjob = kiss_sync_cronjob(podiumd_env, "smoelenboek")
    registry.add("smoelenboek index", lambda: run_cronjob(podiumd_env.kube, cronjob, f"{identificatie}-opruimen"))
    data = {
        "identificatie": identificatie,
        "voornaam": "PodiumD",
        "achternaam": identificatie,
        "emails": [{"email": f"{identificatie}@example.invalid"}],
        "groepen": [{"groepsnaam": ITA_GROEP}],
        "afdelingen": [{"afdelingnaam": afdeling}],
    }
    make_object(objecten, registry, objecttype_url(podiumd_env, "Medewerker"), data)
    run_cronjob(podiumd_env.kube, cronjob, identificatie)
    # Elasticsearch shows new documents only after its next index refresh.
    hits = wait_until(
        lambda: kiss_medewerkers(kiss, urls["kiss"], identificatie, "groep", ITA_GROEP),
        timeout=60,
        description=f"KISS's smoelenboek finds {identificatie} in {ITA_GROEP}",
    )
    hits += kiss_medewerkers(kiss, urls["kiss"], identificatie, "afdeling", afdeling)
    assert [medewerker.get("identificatie") for medewerker in hits] == [identificatie, identificatie]
    actoren = [
        kiss_actor(kiss, urls["kiss"], openklant, registry, "medewerker", identificatie),
        kiss_actor(kiss, urls["kiss"], openklant, registry, "groep", ITA_GROEP),
    ]
    taak = kiss_contactverzoek(kiss, urls["kiss"], openklant, registry, actoren, _adres(registry, "email"))
    assert _actoren_of(taak) == [actor["uuid"] for actor in actoren]
    assert str(taak["toelichting"]) in ita_detail_text(ita, urls["ita"], taak)
