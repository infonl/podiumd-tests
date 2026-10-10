"""ITA as the klantcontactmedewerker: lists, claiming an internetaak and answering it with a klantcontact.

Ported from TA regression 77, 73 and interaction 74 and 180 (with a numeric nummer and the
current add-klantcontact body; the TA versions failed on both). Claiming and answering write
ITA's logboek to Objecten, which needs an edge that buffers request bodies, as nginx does;
KISS reads that logboek with its own Objecten token.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.bootstrap.steps import ITA_GROEP
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.clients.platform import objecten_client
from podiumd_tests.json_data import entries
from podiumd_tests.kcc import ITA_GROUP_ACCESS
from podiumd_tests.kcc import ita_detail_text
from podiumd_tests.kcc import kcc_login
from podiumd_tests.mailpit import forget_mails
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.seed.objecten import clean_up_logboek
from podiumd_tests.seed.objecten import make_object
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openklant import clean_up_klantcontacten
from podiumd_tests.seed.openklant import klantcontact_body
from podiumd_tests.seed.openklant import klantcontacten_about
from podiumd_tests.seed.openklant import make_actor
from podiumd_tests.seed.openklant import make_betrokkene
from podiumd_tests.seed.openklant import make_internetaak
from podiumd_tests.seed.openklant import make_klantcontact
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.requires("ita", "openklant", "keycloak")]


@pytest.fixture(name="ita")
def fixture_ita(page: Page, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> requests.Session:
    """ITA in the KCC test user's session; ITA finds the user's Open Klant actor by e-mail."""
    need_bootstrap(KCC.name, "openklant-actor-kcc")
    return kcc_login(page, podiumd_env, "ita")


@pytest.fixture(scope="module", name="logboek_type")
def fixture_logboek_type(podiumd_env: Environment) -> str:
    """The Activiteitenlog objecttype ITA logs its actions in."""
    return objecttype_url(podiumd_env, "Activiteitenlog")


@pytest.fixture(name="taak")
def fixture_taak(
    openklant: ApiClient, objecten: ApiClient, registry: ResourceRegistry, logboek_type: str
) -> JsonObject:
    """An unassigned internetaak raised by a klantcontact; ITA's logboek of it is cleaned up too."""
    taak = make_internetaak(openklant, registry, make_klantcontact(openklant, registry), [])
    clean_up_logboek(objecten, registry, logboek_type, str(taak["uuid"]))
    return taak


def claim(ita: requests.Session, urls: dict[str, str], taak: JsonObject) -> None:
    """The KCC user claims the internetaak in ITA."""
    response = ita.post(f"{urls['ita']}/api/internetaken/{taak['uuid']}/aan-mij-toewijzen", json={})
    expect_status(response, HTTPStatus.OK, HTTPStatus.CREATED, HTTPStatus.NO_CONTENT)


def test_afdelingen_and_groepen_are_seeded_together(ita: requests.Session, urls: dict[str, str]) -> None:
    """Afdelingen and groepen both answer, and are both empty or both filled (TA reg-77)."""
    afdelingen = get_entries(ita, urls["ita"] + "/api/afdelingen")
    groepen = get_entries(ita, urls["ita"] + "/api/groepen")
    assert bool(afdelingen) == bool(groepen), f"{len(afdelingen)} afdelingen, {len(groepen)} groepen"


@pytest.mark.tc("ITA-024")
def test_claimed_internetaak_is_on_my_list(
    ita: requests.Session, urls: dict[str, str], openklant: ApiClient, taak: JsonObject
) -> None:
    """A claimed internetaak is assigned to the user's actor and on the user's list (TA int-74, reg-73)."""
    claim(ita, urls, taak)
    assert entries(openklant.get(f"internetaken/{taak['uuid']}")["toegewezenAanActoren"])
    mine = get_entries(ita, urls["ita"] + "/api/internetaken/aan-mij-toegewezen")
    assert taak["uuid"] in {str(t.get("uuid")) for t in mine}


def test_answering_an_internetaak_registers_a_klantcontact(
    ita: requests.Session, urls: dict[str, str], openklant: ApiClient, registry: ResourceRegistry, taak: JsonObject
) -> None:
    """Answering an internetaak with a contact registers that klantcontact in Open Klant (TA int-180)."""
    aanleiding = cast("JsonObject", taak["aanleidinggevendKlantcontact"])
    onderwerp = registry.tagged("ita-antwoord")
    antwoord = klantcontact_body(registry, onderwerp=onderwerp, indicatieContactGelukt=False)
    clean_up_klantcontacten(openklant, registry, onderwerp)
    body = {
        "interneTaakId": taak["uuid"],
        "aanleidinggevendKlantcontactUuid": aanleiding["uuid"],
        "klantcontactRequest": {k: v for k, v in antwoord.items() if k != "nummer"},
    }
    response = ita.post(urls["ita"] + "/api/klantcontacten/add-klantcontact", json=body)
    found = klantcontacten_about(openklant, onderwerp)
    assert response.status_code in {HTTPStatus.OK, HTTPStatus.CREATED, HTTPStatus.NO_CONTENT}, describe(response)
    assert [k["indicatieContactGelukt"] for k in found] == [False]


def test_kanalen_answer_the_kcc_user(ita: requests.Session, urls: dict[str, str]) -> None:
    """With a login, ITA lists its kanalen (TA smoke 72; anonymous it refuses, test_api_health)."""
    assert isinstance(expect_status(ita.get(urls["ita"] + "/api/kanalen"), HTTPStatus.OK).json(), list)


@pytest.mark.parametrize("soort", ["Afdeling", "Groep"])
def test_forwarded_internetaak_is_assigned_to_the_afdeling_or_groep(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    ita: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    taak: JsonObject,
    soort: str,
) -> None:
    """Forwarding to an afdeling or groep assigns the internetaak to its Open Klant actor (TA reg-184).

    ITA creates that actor (objectId = the identificatie); TA's actorType/actorIdentifier body gets 400.
    """
    identificatie = registry.tagged(soort.lower())
    data = {"naam": identificatie, "identificatie": identificatie, "email": f"{identificatie}@example.invalid"}
    make_object(objecten, registry, objecttype_url(podiumd_env, soort), data)
    actoren = {"actoridentificatorObjectId": identificatie}
    registry.add(
        f"actoren of {identificatie}",
        lambda: [openklant.delete(str(a["url"])) for a in openklant.list("actoren", actoren)],
    )
    forward = ita.post(f"{urls['ita']}/api/internetaken/{taak['uuid']}/forward", json={soort.lower(): identificatie})
    expect_status(forward, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    # ITA mails the afdeling or groep about the forwarded contactverzoek.
    forget_mails(podiumd_env, registry, f'to:"{data["email"]}"')
    assigned = entries(openklant.get(f"internetaken/{taak['uuid']}")["toegewezenAanActoren"])
    assert {str(a["uuid"]) for a in assigned} & {str(a["uuid"]) for a in openklant.list("actoren", actoren)}


@pytest.mark.requires("kiss", "objecten", "cluster")
@pytest.mark.xfail(
    strict=True,
    reason="reference configuration (ExternalsPodiumD, podiumd-infra, minikube): KISS's Objecten token"
    " (LOGBOEK_TOKEN) has no permission on Activiteitenlog, only ITA's has; Objecten answers 200 with"
    " an empty list, so KISS shows none of ITA's activities",
)
def test_kiss_reads_itas_logboek(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    ita: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    objecten: ApiClient,
    logboek_type: str,
    taak: JsonObject,
) -> None:
    """The logboek entry ITA writes when claiming an internetaak is visible with KISS's logboek token."""
    if not podiumd_env.credentials.configured("kiss_logboek_token"):
        pytest.skip(f"profile {podiumd_env.profile.name} has no secret kiss_logboek_token")
    claim(ita, urls, taak)
    query = {"type": logboek_type, "data_attr": f"heeftBetrekkingOp__objectId__exact__{taak['uuid']}"}
    written = wait_until(lambda: objecten.list("objects", query), timeout=30, description="ITA's logboek entry")
    kiss = objecten_client(podiumd_env, "kiss_logboek_token")
    assert [o["url"] for o in kiss.list("objects", query)] == [o["url"] for o in written]


@pytest.mark.tc("ITA-035")
@ITA_GROUP_ACCESS
def test_contactverzoek_from_kiss_shows_in_full_in_ita(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    ita: requests.Session,
    urls: dict[str, str],
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    logboek_type: str,
    need_bootstrap: Callable[..., None],
) -> None:
    """A contactverzoek as KISS registers it (klantcontact, klant, internetaak to a groep) shows in full in ITA."""
    need_bootstrap("objecten-medewerker-kcc")
    groep = make_actor(openklant, registry, "organisatorische_eenheid", ITA_GROEP, "grp")
    onderwerp = registry.tagged("contactverzoek")
    klantcontact = make_klantcontact(openklant, registry, onderwerp=onderwerp, inhoud=f"Vraag {onderwerp}")
    make_betrokkene(openklant, registry, klantcontact, None)
    taak = make_internetaak(openklant, registry, klantcontact, [groep])
    clean_up_logboek(objecten, registry, logboek_type, str(taak["uuid"]))
    detail = ita_detail_text(ita, urls["ita"], taak)
    assert [v for v in (onderwerp, f"Vraag {onderwerp}", str(taak["toelichting"]), "PodiumD") if v not in detail] == []
