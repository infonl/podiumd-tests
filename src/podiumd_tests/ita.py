"""ITA's calls on a contactverzoek (internetaak) and its lists, as its pages make them; fixtures of ITA's tests."""

from __future__ import annotations

import uuid

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.kcc import kcc_login
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.seed.objecten import clean_up_logboek
from podiumd_tests.seed.objecten import make_object
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openklant import make_internetaak
from podiumd_tests.seed.openklant import make_klantcontact

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Mapping
    from collections.abc import Sequence

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

# ITA accepts page and pageSize from 1 to 100 on its paged lists.
MAX_PAGES = 100
PAGE_SIZE = 100


@pytest.fixture(name="ita")
def fixture_ita(page: Page, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> requests.Session:
    """Return ITA in the KCC test user's session; ITA finds the user's Open Klant actor by e-mail."""
    need_bootstrap(KCC.name, "openklant-actor-kcc")
    return kcc_login(page, podiumd_env, "ita")


@pytest.fixture(scope="session", name="logboek_type")
def fixture_logboek_type(podiumd_env: Environment) -> str:
    """Return the Activiteitenlog objecttype ITA logs its actions in."""
    return objecttype_url(podiumd_env, "Activiteitenlog")


@pytest.fixture(name="internetaak")
def fixture_internetaak(
    openklant: ApiClient, objecten: ApiClient, registry: ResourceRegistry, logboek_type: str
) -> JsonObject:
    """Return an unassigned internetaak (make_contactverzoek)."""
    return make_contactverzoek(openklant, objecten, registry, logboek_type)


def make_contactverzoek(
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    logboek_type: str,
    actoren: Sequence[JsonObject] = (),
) -> JsonObject:
    """Create an internetaak raised by a new klantcontact, assigned to actoren; cleanup also deletes ITA's logboek."""
    taak = make_internetaak(openklant, registry, make_klantcontact(openklant, registry), list(actoren))
    clean_up_logboek(objecten, registry, logboek_type, str(taak["uuid"]))
    return taak


def assign_to_me(ita: requests.Session, ita_url: str, taak: JsonObject) -> None:
    """Assign the internetaak to the logged-in medewerker's Open Klant actor."""
    response = ita.post(f"{ita_url}/api/internetaken/{taak['uuid']}/aan-mij-toewijzen", json={})
    expect_status(response, HTTPStatus.OK, HTTPStatus.CREATED, HTTPStatus.NO_CONTENT)


def answer_body(taak: JsonObject, klantcontact: Mapping[str, object], partij: str | None = None) -> dict[str, object]:
    """Return the body of ITA's add-klantcontact and close-with-klantcontact: a klantcontact answering the internetaak.

    ITA numbers the klantcontact itself; a nummer is left out. partij: the uuid ITA links the klantcontact to.
    """
    body: dict[str, object] = {
        "interneTaakId": taak["uuid"],
        "aanleidinggevendKlantcontactUuid": section(taak, "aanleidinggevendKlantcontact")["uuid"],
        "klantcontactRequest": {key: value for key, value in klantcontact.items() if key != "nummer"},
    }
    if partij:
        body["partijUuid"] = partij
    return body


def close_with_klantcontact(ita: requests.Session, ita_url: str, body: JsonObject) -> JsonObject:
    """Register the klantcontact of answer_body and set the internetaak verwerkt; ITA's result."""
    response = ita.post(f"{ita_url}/api/internetaken/close-with-klantcontact", json=body)
    return cast("JsonObject", expect_status(response, HTTPStatus.CREATED).json())


def my_internetaken(ita: requests.Session, ita_url: str, *, afgerond: bool = False) -> list[JsonObject]:
    """Return Aan mij toegewezen, or Mijn historie when afgerond, as ITA orders it."""
    return get_entries(ita, f"{ita_url}/api/internetaken/aan-mij-toegewezen?afgerond={str(afgerond).lower()}")


def overview(ita: requests.Session, url: str, params: Mapping[str, str] | None = None) -> list[JsonObject]:
    """Return all pages of an ITA overview: Alle contactverzoeken or Afdelings- and Groephistorie.

    LookupError when the list goes on past the last page ITA allows.
    """
    found: list[JsonObject] = []
    for page in range(1, MAX_PAGES + 1):
        query = {**(params or {}), "page": str(page), "pageSize": str(PAGE_SIZE)}
        body = cast("JsonObject", expect_status(ita.get(url, params=query), HTTPStatus.OK).json())
        found += entries(body.get("results"))
        if not body.get("next"):
            return found
    msg = f"{url} lists more than {MAX_PAGES * PAGE_SIZE} contactverzoeken: ITA pages no further"
    raise LookupError(msg)


def afdeling_or_groep_historie(
    ita: requests.Session, ita_url: str, naam: str, *, afgerond: bool = True
) -> list[JsonObject]:
    """Return the contactverzoeken of an afdeling or groep (by its actor's naam): Afdelings- and Groephistorie."""
    params = {"naamActor": naam, "afgerond": str(afgerond).lower()}
    return overview(ita, f"{ita_url}/api/internetaken/afdelingen-groepen", params)


def my_afdelingen_and_groepen(ita: requests.Session, ita_url: str) -> list[str]:
    """Return the names of the logged-in medewerker's afdelingen and groepen, from their Medewerker in Objecten."""
    return strings(expect_status(ita.get(f"{ita_url}/api/gebruiker-groepen-and-afdelingen"), HTTPStatus.OK).json())


def uuids(taken: list[JsonObject]) -> list[str]:
    """Return the uuids of ITA's list items, in their order."""
    return [str(taak.get("uuid")) for taak in taken]


def clean_up_actoren(openklant: ApiClient, registry: ResourceRegistry, object_id: str) -> None:
    """Delete, at cleanup, the Open Klant actoren ITA creates for an afdeling, groep or medewerker it forwards to."""
    query = {"actoridentificatorObjectId": object_id}

    def delete() -> None:
        for actor in openklant.list("actoren", query):
            openklant.delete(str(actor["url"]))

    registry.add(f"actoren of {object_id}", delete)


def mailbox(identificatie: str) -> str:
    """Return the e-mail address the tests give an afdeling, groep or medewerker."""
    return f"{identificatie}@example.invalid"


def make_eenheid(  # noqa: PLR0913  # the clients, cleanup and the eenheid
    env: Environment,
    objecten: ApiClient,
    openklant: ApiClient,
    registry: ResourceRegistry,
    soort: str,
    *,
    with_mailbox: bool,
) -> str:
    """Create an afdeling or groep (soort Afdeling, Groep) in Objecten, with a groepsmailbox or none; its identificatie.

    Its naam is its identificatie, unique: ITA refuses an identificatie that several objects share.
    """
    identificatie = registry.tagged(f"{soort.lower()}-{uuid.uuid4().hex[:8]}")
    data = {"naam": identificatie, "identificatie": identificatie}
    if with_mailbox:
        data["email"] = mailbox(identificatie)
    make_object(objecten, registry, objecttype_url(env, soort), data)
    clean_up_actoren(openklant, registry, identificatie)
    return identificatie


def make_medewerker(  # noqa: PLR0913  # the clients, cleanup and the medewerker's links
    env: Environment,
    objecten: ApiClient,
    openklant: ApiClient,
    registry: ResourceRegistry,
    *,
    with_email: bool,
    afdeling: str | None = None,
    groep: str | None = None,
) -> str:
    """Create a Medewerker in Objecten of the afdeling or groep (by naam), with an e-mail address or none.

    Returns its identificatie.
    """
    identificatie = registry.tagged(f"medewerker-{uuid.uuid4().hex[:8]}")
    data: dict[str, object] = {
        "identificatie": identificatie,
        "voornaam": "PodiumD",
        "achternaam": identificatie,
        "afdelingen": [{"afdelingnaam": afdeling}] if afdeling else [],
        "groepen": [{"groepsnaam": groep}] if groep else [],
    }
    if with_email:
        data["emails"] = [{"email": mailbox(identificatie)}]
    make_object(objecten, registry, objecttype_url(env, "Medewerker"), data)
    clean_up_actoren(openklant, registry, identificatie)
    return identificatie


def forward(ita: requests.Session, ita_url: str, taak: JsonObject, **target: str) -> requests.Response:
    """Forward the internetaak to a medewerker, afdeling or groep (by identificatie) as ITA's Doorsturen tab does."""
    return ita.post(f"{ita_url}/api/internetaken/{taak['uuid']}/forward", json=target)


def medewerkers(ita: requests.Session, ita_url: str, **query: str) -> list[str]:
    """Return the identificaties ITA's medewerker picker offers: by search, or by afdelingOfGroep and type."""
    found = expect_status(ita.get(f"{ita_url}/api/medewerkers", params=query), HTTPStatus.OK).json()
    return [str(medewerker.get("identificatie")) for medewerker in entries(found)]


def koppel_zaak(http: requests.Session, ita_url: str, taak: JsonObject, zaaknummer: str) -> requests.Response:
    """Link the zaak with this identificatie to the klantcontact of the internetaak (Zaak koppelen); ITA's answer."""
    body = {
        "zaakIdentificatie": zaaknummer,
        "aanleidinggevendKlantcontactUuid": section(taak, "aanleidinggevendKlantcontact")["uuid"],
        "internetaakId": taak["uuid"],
    }
    return http.post(f"{ita_url}/api/internetaken/koppel-zaak", json=body)


def logboek(ita: requests.Session, ita_url: str, taak: JsonObject) -> list[JsonObject]:
    """Return the activiteiten of ITA's logboek of the internetaak, newest first, as its detail page shows them."""
    return get_entries(ita, f"{ita_url}/api/internetaken/{taak['uuid']}/logboek")
