"""ITA as the klantcontactmedewerker: forwarding a contactverzoek (Doorsturen) and who gets the mail.

Each test creates its own afdeling, groep and medewerkers in Objecten; ITA creates their Open Klant actoren.
ITA mails one party: the medewerker when they have an e-mail address, otherwise the afdeling's or groep's
groepsmailbox; it refuses a forward when neither has one.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.clients.platform import mailpit_client
from podiumd_tests.ita import assign_to_me
from podiumd_tests.ita import forward
from podiumd_tests.ita import mailbox
from podiumd_tests.ita import make_contactverzoek
from podiumd_tests.ita import make_eenheid
from podiumd_tests.ita import make_medewerker
from podiumd_tests.ita import medewerkers
from podiumd_tests.ita import my_internetaken
from podiumd_tests.ita import uuids
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.mailpit import quoted
from podiumd_tests.mailpit import received
from podiumd_tests.mailpit import search
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openklant import make_actor

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

# Forwarding mails the afdeling, groep or medewerker: only where all mail goes to Mailpit.
pytestmark = [
    pytest.mark.component,
    pytest.mark.ui,
    pytest.mark.requires("ita", "openklant", "objecten", "keycloak", "mailpit"),
]

ITA_E2E = "upstream interne-taak-afhandeling/ITA InterneTaakAfhandeling.EndToEndTest/Contactverzoek"
# ITA sends its mail in the request; Mailpit lists it within seconds.
MAIL_TIMEOUT = 60
SUCCES = "Contactverzoek succesvol doorgestuurd"
# ITA's result when a party without e-mail address could not be mailed although another one was.
NIET_ELKE = "niet elke e-mailnotificatie kon verstuurd worden"
# Forward to a medewerker with their afdeling or groep: (soort, groepsmailbox, medewerker has e-mail).
MEDEWERKER_CASES = {
    "afdeling-with-mailbox": ("Afdeling", True, True),
    "afdeling-without-mailbox": ("Afdeling", False, True),
    "medewerker-without-email": ("Groep", True, False),
}


def _assigned(openklant: ApiClient, taak: JsonObject) -> list[str]:
    """The objectIds of the actoren the internetaak is assigned to in Open Klant, in order."""
    actoren = entries(openklant.get(f"internetaken/{taak['uuid']}")["toegewezenAanActoren"])
    return [str(section(openklant.get(str(a["url"])), "actoridentificator").get("objectId")) for a in actoren]


def _subject(openklant: ApiClient, taak: JsonObject) -> str:
    """The subject of ITA's mail about the forwarded contactverzoek."""
    nummer = openklant.get(str(section(taak, "aanleidinggevendKlantcontact")["url"]))["nummer"]
    return f"Contactverzoek Doorgestuurd - {nummer}"


@pytest.mark.parametrize("soort", ["Afdeling", "Groep"])
@pytest.mark.source(
    "TA regression/184-ita-doorsturen-mutatie.spec.ts",
    "Checks forwarding a contactverzoek in ITA to an afdeling or a groep assigns it there.",
)
@pytest.mark.source(
    f"{ITA_E2E}/ContactverzoekDoorsturenGroepsmailboxScenarios.cs",
    "An afdeling or groep with a groepsmailbox gets the forwarded contactverzoek by mail.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    And a contactverzoek, and an afdeling or groep with a groepsmailbox
    When the medewerker forwards the contactverzoek to the afdeling or groep
    Then the contactverzoek is assigned to it in Open Klant
    And its groepsmailbox gets the mail "Contactverzoek Doorgestuurd" with the klantcontact's nummer
""")
def test_forwarded_internetaak_is_assigned_to_the_afdeling_or_groep(  # fixtures
    ita: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    internetaak: JsonObject,
    soort: str,
) -> None:
    """Forwarding to an afdeling or groep assigns the internetaak to the actor ITA creates for it (TA reg-184).

    TA's actorType/actorIdentifier body gets 400.
    """
    eenheid = make_eenheid(podiumd_env, objecten, openklant, registry, soort, with_mailbox=True)
    response = forward(ita, urls["ita"], internetaak, **{soort.lower(): eenheid})
    assert expect_status(response, HTTPStatus.OK).json()["notificationResult"] == SUCCES
    assert _assigned(openklant, internetaak) == [eenheid]
    subject = _subject(openklant, internetaak)
    received(mailpit_client(podiumd_env), registry, timeout=MAIL_TIMEOUT, to=mailbox(eenheid), subject=subject)


@pytest.mark.parametrize("case", list(MEDEWERKER_CASES))
@pytest.mark.source(
    f"{ITA_E2E}/ContactverzoekDoorsturenScenarios.cs",
    "A contactverzoek is forwarded to a medewerker with their afdeling or groep, also a medewerker without e-mail.",
)
@pytest.mark.source(
    f"{ITA_E2E}/ContactverzoekDoorsturenGroepsmailboxScenarios.cs",
    "Assigned to a medewerker and an afdeling: one recipient, the medewerker before the groepsmailbox.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    And a contactverzoek, and a medewerker of an afdeling or groep
    When the medewerker forwards the contactverzoek to that medewerker and their afdeling or groep
    Then the contactverzoek is assigned to both in Open Klant
    And only the medewerker gets the mail, or the groepsmailbox when the medewerker has no e-mail address
    And ITA warns when the afdeling had no groepsmailbox to mail
""")
def test_forward_to_a_medewerker_mails_one_party(  # fixtures and parameters
    ita: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    internetaak: JsonObject,
    case: str,
) -> None:
    """Forward to medewerker and afdeling or groep: both actoren assigned; ITA mails the medewerker, else the mailbox."""
    soort, eenheid_mailbox, medewerker_email = MEDEWERKER_CASES[case]
    eenheid = make_eenheid(podiumd_env, objecten, openklant, registry, soort, with_mailbox=eenheid_mailbox)
    medewerker = make_medewerker(
        podiumd_env, objecten, openklant, registry, with_email=medewerker_email, **{soort.lower(): eenheid}
    )
    response = forward(ita, urls["ita"], internetaak, medewerker=medewerker, **{soort.lower(): eenheid})
    result = str(expect_status(response, HTTPStatus.OK).json()["notificationResult"])
    if eenheid_mailbox:
        assert result == SUCCES
    else:
        assert NIET_ELKE in result
    assert _assigned(openklant, internetaak) == [medewerker, eenheid]
    mailpit = mailpit_client(podiumd_env)
    to, other = (medewerker, eenheid) if medewerker_email else (eenheid, medewerker)
    received(mailpit, registry, timeout=MAIL_TIMEOUT, to=mailbox(to), subject=_subject(openklant, internetaak))
    assert search(mailpit, f"to:{quoted(mailbox(other))}") == []


@pytest.mark.parametrize("soort", ["Afdeling", "Groep"])
@pytest.mark.source(
    f"{ITA_E2E}/ContactverzoekDoorsturenGroepsmailboxScenarios.cs",
    "Forwarding to an afdeling or groep without groepsmailbox and without medewerker is refused.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    And a contactverzoek, and an afdeling or groep without groepsmailbox
    When the medewerker forwards it to the afdeling or groep without choosing a medewerker
    Then ITA refuses it
    And the contactverzoek stays unassigned in Open Klant
""")
def test_forward_without_any_mailbox_is_refused(  # fixtures
    ita: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    internetaak: JsonObject,
    soort: str,
) -> None:
    """ITA refuses to forward to an afdeling or groep without e-mail address when no medewerker is chosen."""
    eenheid = make_eenheid(podiumd_env, objecten, openklant, registry, soort, with_mailbox=False)
    expect_status(forward(ita, urls["ita"], internetaak, **{soort.lower(): eenheid}), HTTPStatus.BAD_REQUEST)
    assert _assigned(openklant, internetaak) == []


@pytest.mark.parametrize("target", ["medewerker only", "afdeling and groep"])
@pytest.mark.source(
    f"{ITA_E2E}/ContactverzoekDoorsturenScenarios.cs",
    "Mode medewerker without an afdeling or groep cannot be submitted.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    And a contactverzoek
    When the medewerker forwards it to a medewerker without afdeling or groep, or to an afdeling and a groep at once
    Then ITA refuses it
    And the contactverzoek stays unassigned in Open Klant
""")
def test_forward_needs_exactly_one_afdeling_or_groep(  # fixtures
    ita: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    internetaak: JsonObject,
    target: str,
) -> None:
    """ITA's forward takes one afdeling or one groep, with or without a medewerker; other combinations get 400."""
    if target == "medewerker only":
        body = {"medewerker": make_medewerker(podiumd_env, objecten, openklant, registry, with_email=True)}
    else:
        body = {
            soort.lower(): make_eenheid(podiumd_env, objecten, openklant, registry, soort, with_mailbox=True)
            for soort in ("Afdeling", "Groep")
        }
    expect_status(forward(ita, urls["ita"], internetaak, **body), HTTPStatus.BAD_REQUEST)
    assert _assigned(openklant, internetaak) == []


@pytest.mark.source(
    f"{ITA_E2E}/ContactverzoekDoorsturenScenarios.cs",
    "The medewerker picker finds medewerkers by name, and lists those of the chosen afdeling or groep.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    And a medewerker of an afdeling and of a groep
    When the medewerker searches medewerkers by name, by the afdeling and by the groep
    Then ITA offers that medewerker each time
    And a name that matches nobody gives no medewerkers
""")
def test_medewerkers_are_found_by_name_afdeling_and_groep(
    ita: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """GET /api/medewerkers by search, and by afdelingOfGroep with type Afdeling or Groep."""
    afdeling = make_eenheid(podiumd_env, objecten, openklant, registry, "Afdeling", with_mailbox=True)
    groep = make_eenheid(podiumd_env, objecten, openklant, registry, "Groep", with_mailbox=True)
    medewerker = make_medewerker(
        podiumd_env, objecten, openklant, registry, with_email=True, afdeling=afdeling, groep=groep
    )
    assert medewerkers(ita, urls["ita"], search=medewerker) == [medewerker]
    assert medewerkers(ita, urls["ita"], afdelingOfGroep=afdeling, type="Afdeling") == [medewerker]
    assert medewerkers(ita, urls["ita"], afdelingOfGroep=groep, type="Groep") == [medewerker]
    assert medewerkers(ita, urls["ita"], search=registry.tagged("niemand")) == []


@pytest.mark.source(
    f"{ITA_E2E}/ContactverzoekScenarios.cs",
    "Regression #425: a contactverzoek assigned through the user's object-register medewerker id is the user's.",
)
@pytest.mark.scenario("""
    Given a contactverzoek assigned to the KCC medewerker by their identificatie in the medewerker register
    When the medewerker opens their own contactverzoeken in ITA
    Then ITA lists it, so the medewerker need not assign it to themselves
""")
def test_contactverzoek_assigned_by_objectregister_id_is_mine(  # fixtures
    ita: requests.Session,
    urls: dict[str, str],
    openklant: ApiClient,
    registry: ResourceRegistry,
    objecten: ApiClient,
    logboek_type: str,
    need_bootstrap: Callable[..., None],
) -> None:
    """ITA counts an actor mdw/obj/idf with the user's samaccountname as the user's (ITA#425)."""
    need_bootstrap("objecten-medewerker-kcc")
    identificatie = KCC.attributes["samaccountname"][0]
    # ITA's key for a medewerker in the object register (KnownMedewerkerIdentificators.ObjectRegisterId).
    key = {"CodeObjecttype": "mdw", "CodeRegister": "obj", "CodeSoortObjectId": "idf", "ObjectId": identificatie}
    existing = openklant.list("actoren", {f"actoridentificator{name}": value for name, value in key.items()})
    actor = existing[0] if existing else make_actor(openklant, registry, "medewerker", identificatie, "mdw")
    taak = make_contactverzoek(openklant, objecten, registry, logboek_type, [actor])
    assert str(taak["uuid"]) in uuids(my_internetaken(ita, urls["ita"]))
    assign_to_me(ita, urls["ita"], taak)
