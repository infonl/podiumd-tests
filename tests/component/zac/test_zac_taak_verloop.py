"""ZAC's CMMN taken over their life: saved before afronden, reassigned, given documents, dated, and their historie.

All run on the throwaway taken zaaktype, with every human task on.
"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.steps import ZAC_ROLE_USERS
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.responses import expect_status
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import GERELATEERD
from podiumd_tests.zac import LIST_TIMEOUT
from podiumd_tests.zac import is_taak_listed
from podiumd_tests.zac import koppel
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import wijzig_zaak
from podiumd_tests.zac_documents import delete_document
from podiumd_tests.zac_documents import document_url
from podiumd_tests.zac_documents import taak_documents
from podiumd_tests.zac_documents import uploaded_document
from podiumd_tests.zac_taken import ADVIES_INTERN
from podiumd_tests.zac_taken import GOEDKEUREN
from podiumd_tests.zac_taken import complete_task
from podiumd_tests.zac_taken import read_taak
from podiumd_tests.zac_taken import started_taak
from podiumd_tests.zac_taken import taak_historie
from podiumd_tests.zac_taken import toekennen_taak
from podiumd_tests.zac_taken import wijzig_taak

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    # pabc and cluster: fixture zac_taken_zaak's throwaway zaaktype.
    pytest.mark.requires("zac", "openzaak", "keycloak", "pabc", "cluster"),
    pytest.mark.xdist_group("zac-taken-zaaktype"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, taken-cmmn).",
    ),
]

VRAAG = "podiumd-tests vraag"
# A value of ZAC's referentietabel ADVIES; ZAC stores any text.
ADVIES = "Positief"
EARLIER_DAYS = 5


def _advies_intern(zac: requests.Session, zac_url: str, zaak: JsonObject, groep: str) -> JsonObject:
    """Start Advies intern with a vraag for the test admin in the group; the open taak."""
    return started_taak(zac, zac_url, zaak, ADVIES_INTERN, (groep, ADMIN.username), taakdata={"vraag": VRAAG})


@pytest.mark.scenario("""
    Given a zaak in behandeling in ZAC with a document
    When the behandelaar fills in Goedkeuren akkoord, to sign the document, and saves without afronden
    Then the taak keeps the choice and the document
    And the document is not yet ondertekend
""")
def test_saved_goedkeuren_keeps_its_taakdata_until_afronden(
    zac: requests.Session, urls: dict[str, str], behandeling: JsonObject, zac_group: str, registry: ResourceRegistry
) -> None:
    """Opslaan (PUT taakdata) stores the form's taakdata; only afronden signs the documents in ondertekenen."""
    zac_url = urls["zac"]
    document = uploaded_document(zac, zac_url, behandeling, registry, suffix="pdf")
    vraag = {"vraag": VRAAG, "relevanteDocumenten": str(document["uuid"])}
    taak = started_taak(zac, zac_url, behandeling, GOEDKEUREN, (zac_group, ADMIN.username), taakdata=vraag)
    akkoord = {"ondertekenen": str(document["uuid"]), "goedkeuren": "goedkeuren.AKKOORD"}
    wijzig_taak(zac, zac_url, str(taak["id"]), taakdata={**section(taak, "taakdata"), **akkoord})
    opgeslagen = section(read_taak(zac, zac_url, str(taak["id"])), "taakdata")
    assert {key: opgeslagen.get(key) for key in akkoord} == akkoord
    gelezen = expect_status(zac.get(document_url(zac_url, document)), HTTPStatus.OK).json()
    assert "ONDERTEKEND" not in strings(gelezen.get("indicaties"))


@pytest.mark.scenario("""
    Given a zaak in behandeling in ZAC with an open Goedkeuren whose fatale datum is the zaak's
    When the behandelaar moves the zaak's fatale datum 5 days earlier
    Then the taak's fatale datum moves along to the zaak's new one
""")
def test_earlier_zaak_fatale_datum_caps_the_open_taak(
    zac: requests.Session, urls: dict[str, str], behandeling: JsonObject, zac_group: str
) -> None:
    """An earlier uiterlijkeEinddatumAfdoening sets the later due dates of the zaak's open taken to it.

    ZAC leaves Aanvullende informatie out: its fatale datum may pass the zaak's when it suspends the zaak.
    """
    zac_url = urls["zac"]
    taak = started_taak(zac, zac_url, behandeling, GOEDKEUREN, (zac_group, ADMIN.username), taakdata={"vraag": VRAAG})
    einde = date.fromisoformat(str(behandeling["uiterlijkeEinddatumAfdoening"]))
    assert taak.get("fataledatum") == einde.isoformat()
    eerder = (einde - timedelta(days=EARLIER_DAYS)).isoformat()
    expect_status(wijzig_zaak(zac, zac_url, behandeling, uiterlijkeEinddatumAfdoening=eerder), HTTPStatus.OK)
    assert read_taak(zac, zac_url, str(taak["id"])).get("fataledatum") == eerder


@pytest.mark.scenario("""
    Given a zaak in behandeling in ZAC with an open Advies intern
    When the behandelaar adds a document from the taak
    Then the taak lists the document, and the zaak has it
    When the behandelaar deletes the document
    Then the taak still opens, and lists no document
""")
def test_taak_lists_its_document_until_it_is_deleted(
    zac: requests.Session, urls: dict[str, str], behandeling: JsonObject, zac_group: str, registry: ResourceRegistry
) -> None:
    """An upload with taakObject adds the document to taakdocumenten; ZAC skips a deleted one when it lists them."""
    zac_url = urls["zac"]
    taak = _advies_intern(zac, zac_url, behandeling, zac_group)
    document = uploaded_document(zac, zac_url, behandeling, registry, status="in_bewerking", taak=taak)
    met_document = read_taak(zac, zac_url, str(taak["id"]))
    assert strings(met_document.get("taakdocumenten")) == [document["uuid"]]
    assert [item.get("uuid") for item in taak_documents(zac, zac_url, met_document)] == [document["uuid"]]

    expect_status(delete_document(zac, zac_url, behandeling, document), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert taak_documents(zac, zac_url, read_taak(zac, zac_url, str(taak["id"]))) == []


@pytest.mark.scenario("""
    Given a zaak in behandeling in ZAC with an open Advies intern for the test admin
    When the test admin assigns the taak to another behandelaar with a reden
    Then the taak is in that behandelaar's Mijn taken
    When the test admin completes the taak
    Then the taak's historie shows the change of behandelaar with the reden, and the taak afgerond
""")
def test_taak_historie_shows_its_reassignment_and_completion(
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    behandeling: JsonObject,
    zac_group: str,
) -> None:
    """Toekennen moves the taak to the new behandelaar's Mijn taken; GET taken/{id}/historie lists each change."""
    zac_url = urls["zac"]
    taak = _advies_intern(zac, zac_url, behandeling, zac_group)
    naam = ZAC_ROLE_USERS["behandelaar"].username
    toekennen_taak(zac, zac_url, taak, zac_group, naam)
    wait_until(
        lambda: is_taak_listed(zac_as("behandelaar"), zac_url, taak, alleenMijnTaken=True),
        timeout=LIST_TIMEOUT,
        description=f"taak {taak['id']} in Mijn taken of {naam}",
    )
    complete_task(zac, zac_url, read_taak(zac, zac_url, str(taak["id"])), {"advies": ADVIES})

    regels = taak_historie(zac, zac_url, taak)
    assert ("aangemaakt", "afgerond") in _statussen(regels), regels
    behandelaars = [regel for regel in regels if regel.get("attribuutLabel") == "behandelaar"]
    assert "podiumd-tests" in {regel.get("toelichting") for regel in behandelaars}, regels


@pytest.mark.scenario("""
    Given a zaak in behandeling in ZAC
    When the behandelaar starts Advies intern
    Then the taak's historie shows it aangemaakt
""")
def test_taak_historie_shows_it_aangemaakt(
    zac: requests.Session, urls: dict[str, str], behandeling: JsonObject, zac_group: str
) -> None:
    """ZAC turns Flowable's USER_TASK_CREATED log entry into the historie line taak.status aangemaakt."""
    taak = _advies_intern(zac, urls["zac"], behandeling, zac_group)
    regels = taak_historie(zac, urls["zac"], taak)
    assert (None, "aangemaakt") in _statussen(regels), regels


def _statussen(regels: list[JsonObject]) -> set[tuple[object, object]]:
    """The (old, new) values of the historie's taak.status lines."""
    return {
        (regel.get("oudeWaarde"), regel.get("nieuweWaarde"))
        for regel in regels
        if regel.get("attribuutLabel") == "taak.status"
    }


@pytest.mark.scenario("""
    Given a zaak in its intake in ZAC with an open Aanvullende informatie
    When the behandelaar links another zaak to it as gerelateerd
    Then the zaak shows the other zaak as gerelateerd
""")
def test_zaak_with_open_aanvullende_informatie_is_gekoppeld(
    zac: requests.Session,
    urls: dict[str, str],
    zac_taken_zaak: Callable[[], JsonObject],
    start_taak: Callable[..., JsonObject],
) -> None:
    """Koppelen after Aanvullende informatie; the other order is in test_aanvullende_informatie_with_opschorten_*."""
    zac_url = urls["zac"]
    zaak, ander = zac_taken_zaak(), zac_taken_zaak()
    start_taak(zaak)
    expect_status(koppel(zac, zac_url, zaak, ander, GERELATEERD), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    gekoppeld = entries(read_zaak(zac, zac_url, str(zaak["uuid"])).get("gerelateerdeZaken"))
    assert (ander["identificatie"], GERELATEERD) in {
        (item.get("identificatie"), item.get("relatieType")) for item in gekoppeld
    }
