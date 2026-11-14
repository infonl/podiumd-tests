"""Chain: Open Formulieren's klantprofiel shows a burger's e-mail address and telefoonnummer from Open Klant, and
writes the new ones back.

The burger logs in with DigiD (Keycloak's mock) as a person of the BRP test set, so ZAC shows the person with
Open Klant's voorkeur. Open Formulieren takes a new e-mail address only with the code it mails to it.
"""

from __future__ import annotations

import secrets

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import KOOYMAN
from podiumd_tests.json_data import entries
from podiumd_tests.mailpit import own_address
from podiumd_tests.mailpit import received
from podiumd_tests.openformulieren import communication_preferences
from podiumd_tests.openformulieren import complete_submission
from podiumd_tests.openformulieren import logged_in_submission
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import verify_email
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openklant import clean_up_klantcontacten
from podiumd_tests.seed.openklant import delete_partij
from podiumd_tests.seed.openklant import expanded
from podiumd_tests.seed.openklant import make_digitaal_adres
from podiumd_tests.seed.openklant import make_partij
from podiumd_tests.seed.openklant import make_partij_identificator
from podiumd_tests.seed.openklant import partijen_of
from podiumd_tests.seed.openzaak import today
from podiumd_tests.zac import person_key

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires("openformulieren", "openklant", "keycloak", "zac", "mailpit", "cluster"),
]

TIMEOUT = 90
PROFIEL = {
    "type": "customerProfile",
    "key": "profiel",
    "label": "Contactgegevens",
    "digitalAddressTypes": ["email", "phoneNumber"],
    "shouldUpdateCustomerData": True,
}


def voorkeuren(openklant_url: str) -> JsonObject:
    """Return the form variable that Open Formulieren fills with the klantprofiel's addresses from Open Klant."""
    options = {
        "customer_interactions_api_group": f"{openklant_url}/klantinteracties/api/v1/",
        "profile_form_variable": PROFIEL["key"],
    }
    return {
        "key": "voorkeuren",
        "data_type": "array",
        "prefill_plugin": "communication_preferences",
        "prefill_options": options,
    }


def offered(preferences: list[JsonObject]) -> dict[str, tuple[object, ...]]:
    """Return per type the addresses the klantprofiel offers and its voorkeur."""
    return {
        str(channel["type"]): ([str(option["address"]) for option in entries(channel["options"])], channel["preferred"])
        for channel in preferences
    }


def new_telefoonnummer() -> str:
    """Return a random mobile telefoonnummer."""
    return f"06{secrets.randbelow(10**8):08d}"


@pytest.fixture(name="persoon")
def fixture_persoon(openklant: ApiClient, registry: ResourceRegistry) -> tuple[str, str, str]:
    """A partij of KOOYMAN in Open Klant with a verified e-mail address and a telefoonnummer as voorkeur.

    Returns its URL, e-mail address and telefoonnummer; cleanup deletes it with the addresses Open Formulieren adds.
    """
    partij = make_partij(openklant, registry)
    url = str(partij["url"])
    registry.add(f"partij {url} with its addresses", lambda: delete_partij(openklant, url))
    make_partij_identificator(openklant, registry, partij, "bsn", KOOYMAN)
    assert partijen_of(openklant, KOOYMAN) == [url], f"other Open Klant partijen have BSN {KOOYMAN}"
    email, telefoon = own_address(registry), new_telefoonnummer()
    make_digitaal_adres(openklant, registry, partij, email, verificatieDatum=today())
    make_digitaal_adres(openklant, registry, partij, telefoon)
    return url, email, telefoon


def zac_contactgegevens(zac: requests.Session, zac_url: str, bsn: str) -> tuple[object, object]:
    """Return the e-mail address and telefoonnummer ZAC shows for the person."""
    persoon = expect_status(zac.get(f"{zac_url}/rest/klanten/person/{person_key(zac, zac_url, bsn)}"), HTTPStatus.OK)
    shown = persoon.json()
    return shown.get("emailadres"), shown.get("telefoonnummer")


@pytest.mark.source(
    "upstream open-formulieren/open-forms src/openforms/contrib/customer_interactions/tests",
    "A logged-in burger's new preferred addresses go to Open Klant; a new e-mail address only once verified.",
)
@pytest.mark.scenario("""
    Given a person in Open Klant with a verified e-mail address and a telefoonnummer as voorkeur
    When the person logs in with DigiD on a form with a klantprofiel
    Then the form offers that e-mail address and telefoonnummer as voorkeur
    When the person verifies a new e-mail address, enters a new telefoonnummer, makes both the voorkeur and submits
    Then Open Klant has both as the person's voorkeur and a klantcontact about the submission
    And ZAC shows the new e-mail address and telefoonnummer for the person
""")
def test_klantprofiel_writes_new_voorkeur_to_open_klant(
    podiumd_env: Environment,
    urls: dict[str, str],
    zac: requests.Session,
    openklant: ApiClient,
    mailpit: ApiClient,
    registry: ResourceRegistry,
    persoon: tuple[str, str, str],
    need_bootstrap: Callable[..., None],
) -> None:
    """The klantprofiel offers Open Klant's addresses; the new voorkeur reaches Open Klant and ZAC."""
    need_bootstrap("openformulieren-oidc-mock")
    partij, email, telefoon = persoon
    slug = registry.tagged("klantprofiel")
    make_form(podiumd_env, registry, slug, [PROFIEL], {}, ("digid_oidc",), variables=[voorkeuren(urls["openklant"])])
    clean_up_klantcontacten(openklant, registry, slug)
    http, submission, headers = logged_in_submission(podiumd_env, registry, slug, "digid_oidc", {"bsn": [KOOYMAN]})
    shown = communication_preferences(http, urls["openformulieren"], submission, headers, str(PROFIEL["key"]))
    assert offered(shown) == {"email": ([email], email), "phoneNumber": ([telefoon], telefoon)}

    nieuw = {"email": own_address(registry), "phoneNumber": new_telefoonnummer()}
    verify_email(
        http,
        submission,
        headers,
        ("profiel", nieuw["email"]),
        lambda to: received(mailpit, registry, timeout=TIMEOUT, to=to),
    )
    profiel = [
        {"type": soort, "address": adres, "preferenceUpdate": "isNewPreferred"} for soort, adres in nieuw.items()
    ]
    complete_submission(podiumd_env, http, submission, headers, {"profiel": profiel}, timeout=TIMEOUT)

    adressen = expanded(openklant, partij, "digitaleAdressen")
    voorkeur = {str(a["soortDigitaalAdres"]): a["adres"] for a in adressen if a.get("isStandaardAdres")}
    assert voorkeur == {"email": nieuw["email"], "telefoonnummer": nieuw["phoneNumber"]}, adressen
    assert [c.get("kanaal") for c in openklant.list("klantcontacten", {"onderwerp": slug})] == ["Webformulier"]
    assert zac_contactgegevens(zac, urls["zac"], KOOYMAN) == (nieuw["email"], nieuw["phoneNumber"])
