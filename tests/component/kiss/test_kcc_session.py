"""KISS as the klantcontactmedewerker: a session with the KCC role, and klantcontacten through KISS.

Ported from TA smoke 06 and 113, and regression 12 and 100.
"""

from __future__ import annotations

import json

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.auth.keycloak_admin import user_email
from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.basisregistraties import KVK_TEST_NUMMER
from podiumd_tests.bootstrap.kiss import KANALEN
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kcc import KENNIS_URL
from podiumd_tests.kcc import kcc_login
from podiumd_tests.kcc import kiss_betrokkene
from podiumd_tests.kcc import kiss_contactmomentdetails
from podiumd_tests.kcc import kiss_klantcontact
from podiumd_tests.kcc import kiss_klantcontacten
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.seed.openklant import klantcontact_body
from podiumd_tests.seed.openklant import make_organisatie
from podiumd_tests.seed.openklant import make_partij

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.core, pytest.mark.requires("kiss", "keycloak")]

# KISS names the medewerker by the token's email claim, else by preferred_username (AuthenticationSetup.GetEmail).
KCC_IDS = (user_email(KCC.username), KCC.username)


def _is_the_kcc_medewerker(actor: JsonObject) -> bool:
    return section(actor, "actoridentificator").get("objectId") in KCC_IDS


@pytest.fixture(name="kiss")
def fixture_kiss(page: Page, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> requests.Session:
    """KISS in the KCC test user's session."""
    need_bootstrap(KCC.name)
    return kcc_login(page, podiumd_env, "kiss")


@pytest.mark.tc("KI-002")
@pytest.mark.source(
    "TA smoke/113-kiss-kcc-login-flow.spec.ts",
    "Checks the KCC employee's login on KISS and that the BFF routes answer after it.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to KISS
    When KISS is asked who is logged in
    Then KISS knows the user as logged in and as klantcontactmedewerker
""")
def test_kcc_user_is_a_klantcontactmedewerker(kiss: requests.Session, urls: dict[str, str]) -> None:
    """KISS knows the logged-in user as a klantcontactmedewerker (TA smoke 113)."""
    me = expect_status(kiss.get(f"{urls['kiss']}/api/me"), HTTPStatus.OK).json()
    assert me["isLoggedIn"]
    assert me["isKcm"]


@pytest.mark.tc("KI-001")
@pytest.mark.source(
    "TA smoke/06-kiss-bff-healthz.spec.ts",
    "KISS smoke test: the BFF answers and the homepage renders; a precondition for every KISS case.",
)
@pytest.mark.source(
    "TA regression/100-kiss-frontend-basis.spec.ts",
    "Checks KISS's frontend and the BFF routes a KCC employee meets, such as /api/me, without a login.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to KISS
    When the medewerker opens KISS's home page
    Then the page shows the Zoeken button and the Uitloggen link
""")
@pytest.mark.usefixtures("kiss")  # logs the page in
def test_kiss_renders_for_the_kcc_user(page: Page, urls: dict[str, str]) -> None:
    """After the login KISS's single-page app renders its search and navigation (TA smoke 06, reg-100)."""
    page.goto(f"{urls['kiss']}/")
    expect(page.get_by_role("banner").get_by_role("button", name="Zoeken")).to_be_visible()
    expect(page.get_by_role("link", name="Uitloggen")).to_be_visible()


@pytest.mark.source(
    "TA regression/12-kiss-bff-kcc-flow.spec.ts",
    "A KCC employee logs in through Keycloak and registers a klantcontact in Open Klant through KISS's BFF.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to KISS
    When the medewerker registers a klantcontact through KISS
    Then the klantcontact is in Open Klant with its onderwerp
""")
def test_klantcontact_through_kiss(  # noqa: FNE008  # the name is the test id
    kiss: requests.Session, urls: dict[str, str], openklant: ApiClient, registry: ResourceRegistry
) -> None:
    """A klantcontact registered through KISS lands in Open Klant (TA reg-12)."""
    body = klantcontact_body(registry, onderwerp=registry.tagged("kiss-klantcontact"))
    assert kiss_klantcontact(kiss, urls["kiss"], openklant, registry, body)["onderwerp"] == body["onderwerp"]


@pytest.mark.source(
    "upstream KISS-frontend Kiss.Bff.EndToEndTest AfhandelingFormScenarios",
    "KISS saves a contactmoment through its own route, which names the logged-in medewerker as actor.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to KISS
    When the medewerker saves a contactmoment as KISS's frontend does
    Then Open Klant has the contactmoment with the medewerker as its actor
""")
def test_contactmoment_saved_in_kiss_names_the_medewerker(
    kiss: requests.Session, urls: dict[str, str], openklant: ApiClient, registry: ResourceRegistry
) -> None:
    """POST /api/postklantcontacten links the KCC user's medewerker actor."""
    body = klantcontact_body(registry, onderwerp=registry.tagged("kiss-medewerker"))
    saved = kiss_klantcontact(kiss, urls["kiss"], openklant, registry, body)
    actoren = [openklant.get(str(actor["url"])) for actor in entries(saved.get("hadBetrokkenActoren"))]
    assert [(actor.get("soortActor"), _is_the_kcc_medewerker(actor)) for actor in actoren] == [("medewerker", True)]


@pytest.mark.parametrize("soort", ["persoon", "organisatie"])
@pytest.mark.source(
    "upstream KISS-frontend Kiss.Bff.EndToEndTest ContactMomentCreation",
    "A contactmoment for a person or a vestiging shows on that klant's Contactmomenten tab.",
)
@pytest.mark.scenario("""
    Given a person or an organisation known in Open Klant
    When the KCC medewerker saves a contactmoment for that klant in KISS
    Then KISS lists the contactmoment for that klant
""")
def test_contactmoment_for_a_klant_is_listed_for_that_klant(  # fixtures
    kiss: requests.Session,
    urls: dict[str, str],
    openklant: ApiClient,
    registry: ResourceRegistry,
    soort: str,
) -> None:
    """A contactmoment with the partij as betrokkene is in KISS's klantcontacten of that partij."""
    partij = make_partij(openklant, registry) if soort == "persoon" else make_organisatie(openklant, registry)
    body = klantcontact_body(registry, onderwerp=registry.tagged(f"kiss-{soort}"))
    saved = kiss_klantcontact(kiss, urls["kiss"], openklant, registry, body)
    kiss_betrokkene(kiss, urls["kiss"], saved, partij)
    listed = kiss_klantcontacten(kiss, urls["kiss"], hadBetrokkene__wasPartij__url=str(partij["url"]))
    assert saved["uuid"] in [item.get("uuid") for item in listed]


@pytest.mark.source(
    "upstream KISS-frontend Kiss.Bff.EndToEndTest AfhandelingFormScenarios, VraagScenarios",
    "KISS keeps a contactmoment's gespreksresultaat, afdeling, vraag and the sources consulted in its own database.",
)
@pytest.mark.scenario("""
    Given a contactmoment the KCC medewerker saved in KISS
    When KISS stores its gespreksresultaat, afdeling, vraag and the VAC and kennisartikel consulted
    Then KISS gives them back for that contactmoment, with the medewerker who registered it
""")
def test_kiss_keeps_the_contactmoment_details(
    kiss: requests.Session, urls: dict[str, str], openklant: ApiClient, registry: ResourceRegistry
) -> None:
    """PUT /api/contactmomentdetails is read back by GET; KISS adds the medewerker (it does not return bronnen)."""
    saved = kiss_klantcontact(kiss, urls["kiss"], openklant, registry, klantcontact_body(registry))
    bronnen = [
        {"soort": "VAC", "titel": registry.tagged("vac"), "url": f"{KENNIS_URL}vac"},
        {"soort": "Kennisbank", "titel": registry.tagged("kennisartikel"), "url": f"{KENNIS_URL}kennis"},
    ]
    fields = {
        "gespreksresultaat": "Afgehandeld",
        "verantwoordelijkeAfdeling": registry.tagged("afdeling"),
        "vraag": "podiumd-tests",
        "specifiekeVraag": registry.tagged("vraag"),
        "bronnen": bronnen,
    }
    details = kiss_contactmomentdetails(kiss, urls["kiss"], saved, **fields)
    kept = {key: details.get(key) for key in ("gespreksresultaat", "verantwoordelijkeAfdeling", "specifiekeVraag")}
    assert kept == {key: fields[key] for key in kept}
    assert details.get("emailadresKcm") in KCC_IDS


@pytest.mark.tc("KI-007")
@pytest.mark.source("draaiboek KI-007", "A person not known in Contact can be found through Haal Centraal.")
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to KISS
    When the medewerker searches a person in the BRP test set by BSN
    Then KISS finds exactly that person, by name
""")
def test_person_unknown_to_kiss_is_found_in_the_brp(kiss: requests.Session, urls: dict[str, str]) -> None:
    """KISS finds a person by BSN through its Haal Centraal BRP proxy.

    KISS rewrites the request body and keeps its Content-Length, so the JSON must be compact, as
    KISS's own frontend sends it.
    """
    query = {"type": "RaadpleegMetBurgerservicenummer", "burgerservicenummer": [EREBOS], "fields": ["naam"]}
    found = kiss.post(
        f"{urls['kiss']}/api/haalcentraal/brp/personen",
        data=json.dumps(query, separators=(",", ":")),
        headers={"Content-Type": "application/json"},
    )
    personen = entries(expect_status(found, HTTPStatus.OK).json()["personen"])
    assert [section(p, "naam").get("voornamen") for p in personen] == ["Erebos"]


@pytest.mark.tc("KI-013")
@pytest.mark.source("draaiboek KI-013", "A company not known in Contact can be found through KvK.")
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to KISS
    When the medewerker searches the KvK test company by its KvK number
    Then KISS finds the company
""")
def test_company_unknown_to_kiss_is_found_in_the_kvk(kiss: requests.Session, urls: dict[str, str]) -> None:
    """KISS finds a company by KvK number through its KvK proxy."""
    found = expect_status(kiss.get(f"{urls['kiss']}/api/kvk/v2/zoeken", params={"kvkNummer": KVK_TEST_NUMMER}), 200)
    assert KVK_TEST_NUMMER in {str(r.get("kvkNummer")) for r in entries(found.json()["resultaten"])}


@pytest.mark.tc("KI-053", "KI-054", "KI-055")
@pytest.mark.parametrize("kanaal", KANALEN)
@pytest.mark.source("draaiboek KI-053", "A contact on kanaal Balie arrives exactly as registered.")
@pytest.mark.source("draaiboek KI-054", "A contact on kanaal Telefoon arrives exactly as registered.")
@pytest.mark.source("draaiboek KI-055", "A contact on kanaal Internet arrives exactly as registered.")
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to KISS
    And KISS offers the kanaal (Balie, Telefoon or Internet)
    When the medewerker registers a klantcontact on that kanaal through KISS
    Then the klantcontact is in Open Klant on exactly that kanaal
""")
def test_klantcontact_keeps_the_kanaal_chosen_in_kiss(  # noqa: FNE008  # the name is the test id
    kiss: requests.Session,
    urls: dict[str, str],
    openklant: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
    kanaal: str,
) -> None:
    """A klantcontact registered through KISS on a kanaal KISS offers lands in Open Klant on exactly that kanaal."""
    need_bootstrap("kiss-kanalen")
    offered = {str(k["naam"]) for k in get_entries(kiss, f"{urls['kiss']}/api/KanalenContactmomentKeuzelijst")}
    if kanaal not in offered:
        pytest.skip(
            f"KISS offers no kanaal {kanaal}: add it in KISS (Beheer, Kanalen) or set profile setting kiss_kanalen"
        )
    body = klantcontact_body(registry, kanaal=kanaal, onderwerp=registry.tagged(f"kanaal-{kanaal.lower()}"))
    assert kiss_klantcontact(kiss, urls["kiss"], openklant, registry, body)["kanaal"] == kanaal
