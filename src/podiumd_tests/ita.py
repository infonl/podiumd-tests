"""ITA's calls on a contactverzoek (internetaak) and its lists, as its pages make them; fixtures of ITA's tests."""

from __future__ import annotations

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
