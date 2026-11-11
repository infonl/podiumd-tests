"""ZAC's CMMN human tasks: Aanvullende informatie in the intake; Goedkeuren, Advies intern, Advies extern and
Document verzenden in behandeling. Started, in Mijn taken, distributed, released and completed.

Partly ported from ZAC's own e2e features taken-toevoegen and taken-verdelen-vrijgeven, through the REST API its UI
calls. The taken in behandeling run on a throwaway zaaktype with every human task on: the estate's zaaktypen keep
their own.
"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.mailpit import own_address
from podiumd_tests.mailpit import received_message
from podiumd_tests.responses import expect_status
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import LIST_TIMEOUT
from podiumd_tests.zac import afronden_intake
from podiumd_tests.zac import assignment
from podiumd_tests.zac import complete_task
from podiumd_tests.zac import human_tasks_offered
from podiumd_tests.zac import is_taak_listed
from podiumd_tests.zac import open_task
from podiumd_tests.zac import read_taak
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import start_human_task
from podiumd_tests.zac import user_events_offered
from podiumd_tests.zac_beheer import referentietabel
from podiumd_tests.zac_beheer import referentietabel_values
from podiumd_tests.zac_documents import document_url
from podiumd_tests.zac_documents import uploaded_document
from podiumd_tests.zac_documents import zaak_documents

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

# ZAC's statustype omschrijvingen while a task Aanvullende informatie is open, and after (ConfigurationService).
WAITING = "Wacht op aanvullende informatie"
INTAKE = "Intake"

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "openzaak", "keycloak")]

ZAC_TEAM = pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, taken-cmmn).",
)
# Fixture zac_taken_zaaktype: a throwaway zaaktype made known to PABC and deleted with a Django snippet, one per run.
THROWAWAY = pytest.mark.requires("pabc", "cluster")
TAKEN_ZAAKTYPE = pytest.mark.xdist_group("zac-taken-zaaktype")
TOELICHTING = "podiumd-tests toelichting"
# A value of ZAC's referentietabel ADVIES; ZAC stores any text.
ADVIES = "Positief"
VRAAG = "podiumd-tests vraag"

# ZAC starts the zaak's CMMN case, and runs list distributions and indexing, in the background.
SUSPENSION_DAYS = 7

# The names of ZAC's CMMN human tasks (Generiek_zaakafhandelmodel.cmmn.xml).
AANVULLENDE_INFORMATIE = "Aanvullende informatie"
GOEDKEUREN = "Goedkeuren"
ADVIES_INTERN = "Advies intern"
ADVIES_EXTERN = "Advies extern"
DOCUMENT_VERZENDEN = "Document verzenden"
MAIL_TIMEOUT = 60


def _started(
    zac: requests.Session, zac_url: str, zaak: JsonObject, name: str, groep: str, **fields: object
) -> JsonObject:
    """Start the human task for the test admin in the group; the open task."""
    admin = {"id": ADMIN.username, "naam": ADMIN.username}
    response = start_human_task(zac, zac_url, zaak, name, groep, medewerker=admin, **fields)
    expect_status(response, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    return open_task(zac, zac_url, str(zaak["uuid"]), name)


@pytest.fixture(name="start_taak")
def fixture_start_taak(
    zac: requests.Session,
    urls: dict[str, str],
    zac_group: str,
    need_bootstrap: Callable[..., None],
) -> Callable[..., JsonObject]:
    """Start the task Aanvullende informatie on a zaak for the test admin in its group, without a mail.

    fields: more of ZAC's RESTHumanTaskData, e.g. taakdata zaakOpschorten with a fataledatum.
    """
    need_bootstrap("zac-aanvullende-informatie")

    def start(zaak: JsonObject, **fields: object) -> JsonObject:
        return _started(zac, urls["zac"], zaak, AANVULLENDE_INFORMATIE, zac_group, **fields)

    return start


@pytest.fixture(name="taak")
def fixture_taak(zac_zaak: Callable[..., JsonObject], start_taak: Callable[..., JsonObject]) -> JsonObject:
    """The task Aanvullende informatie, started on a new zaak."""
    return start_taak(zac_zaak())


@pytest.mark.source(
    "ZAC features/5-taken-toevoegen.feature",
    "Lacking information to finish the intake, Bob assigns an Aanvullende informatie task, which the assignee sees in Mijn taken.",
)
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar starts the taak Aanvullende informatie for a group and a behandelaar
    Then the taak has that group and behandelaar
    And the taak is listed in Mijn taken
""")
def test_started_task_is_in_mijn_taken(
    zac: requests.Session, urls: dict[str, str], taak: JsonObject, zac_group: str
) -> None:
    """The started task has the chosen group and behandelaar, and ZAC's Mijn taken lists it."""
    assert assignment(taak) == (zac_group, ADMIN.username)
    wait_until(
        lambda: is_taak_listed(zac, urls["zac"], taak, alleenMijnTaken=True),
        timeout=LIST_TIMEOUT,
        description=f"task {taak['id']} in Mijn taken",
    )


@pytest.mark.source(
    "ZAC features/5-taken-toevoegen.feature",
    "When Intake lacks information, a task Aanvullende informatie gives the zaak status 'Wacht op aanvullende informatie'.",
)
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar starts the taak Aanvullende informatie on it
    Then the zaak has the status Wacht op aanvullende informatie
""")
def test_aanvullende_informatie_gives_the_zaak_its_waiting_status(
    zac: requests.Session, urls: dict[str, str], taak: JsonObject
) -> None:
    """ZAC sets the zaak's status when the task Aanvullende informatie starts (AanvullendeInformatieTaskListener)."""

    def status() -> str | None:
        naam = section(read_zaak(zac, urls["zac"], str(taak["zaakUuid"])), "status").get("naam")
        return str(naam) if naam == WAITING else None

    wait_until(status, timeout=LIST_TIMEOUT, description=f"status {WAITING!r} on {taak['zaakIdentificatie']}")


@pytest.mark.source(
    "ZAC features/7-taken-verdelen-vrijgeven.feature",
    "Bob assigns selected taken from the werkvoorraad to a group and user, and releases them.",
)
@pytest.mark.scenario("""
    Given a taak Aanvullende informatie on a zaak in ZAC, assigned to a behandelaar
    When the behandelaar releases the taak from the list
    Then the taak keeps its group but has no behandelaar
    When the behandelaar assigns the taak from the list to the group and a behandelaar
    Then the taak has that group and behandelaar again
""")
def test_taken_from_the_list_are_released_and_assigned(
    zac: requests.Session, urls: dict[str, str], taak: JsonObject, zac_group: str
) -> None:
    """Vrijgeven takes the behandelaar away from the selected task; verdelen gives it back."""
    taken = f"{urls['zac']}/rest/taken"
    selected = [{"taakId": taak["id"], "zaakUuid": taak["zaakUuid"]}]

    def is_(wanted: tuple[object, object]) -> bool:
        return assignment(read_taak(zac, urls["zac"], str(taak["id"]))) == wanted

    expect_status(zac.put(f"{taken}/lijst/vrijgeven", json={"taken": selected, "reden": "test"}), 200, 204)
    wait_until(lambda: is_((zac_group, None)), timeout=LIST_TIMEOUT, description=f"task {taak['id']} vrijgegeven")
    body = {"taken": selected, "groepId": zac_group, "behandelaarGebruikersnaam": ADMIN.username, "reden": "test"}
    expect_status(zac.put(f"{taken}/lijst/verdelen", json=body), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    wait_until(
        lambda: is_((zac_group, ADMIN.username)), timeout=LIST_TIMEOUT, description=f"task {taak['id']} verdeeld"
    )


@pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, zaak-lifecycle).",
)
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar starts the taak Aanvullende informatie with opschorten until its fatale datum
    Then the zaak is opgeschort, and its uiterlijke einddatum afdoening moved by those days
    When the behandelaar completes the taak with hervatten
    Then the zaak is no longer opgeschort, and its date moved back by the days not used
""")
def test_aanvullende_informatie_with_opschorten_suspends_until_hervatten(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    start_taak: Callable[..., JsonObject],
) -> None:
    """zaakOpschorten suspends the zaak until the task's fatale datum; zaakHervatten on completion resumes it."""
    zaak = zac_zaak()
    original = date.fromisoformat(str(zaak["uiterlijkeEinddatumAfdoening"]))
    fataledatum = date.today() + timedelta(days=SUSPENSION_DAYS)  # noqa: DTZ011  # ZAC's local date
    taak = start_taak(zaak, fataledatum=fataledatum.isoformat(), taakdata={"zaakOpschorten": "true"})
    opgeschort = read_zaak(zac, urls["zac"], str(zaak["uuid"]))
    assert opgeschort["isOpgeschort"] is True
    moved = date.fromisoformat(str(opgeschort["uiterlijkeEinddatumAfdoening"]))
    assert moved == original + timedelta(days=SUSPENSION_DAYS)

    complete_task(zac, urls["zac"], taak, {"zaakHervatten": "true"})
    hervat = read_zaak(zac, urls["zac"], str(zaak["uuid"]))
    assert hervat["isOpgeschort"] is False
    assert hervat["uiterlijkeEinddatumAfdoening"] == original.isoformat()


@pytest.fixture(name="behandeling")
def fixture_behandeling(
    zac: requests.Session, urls: dict[str, str], zac_taken_zaak: Callable[[], JsonObject]
) -> JsonObject:
    """A zaak of the taken zaaktype after an ontvankelijk intake: in behandeling."""
    zaak = zac_taken_zaak()
    afronden_intake(zac, urls["zac"], zaak)
    return zaak


def _acties(zac: requests.Session, zac_url: str, zaak: JsonObject) -> set[str]:
    """The CMMN user events ZAC offers on the zaak now."""
    offered = user_events_offered(zac, zac_url, str(zaak["uuid"]))
    return set(strings([item.get("userEventListenerActie") for item in offered]))


def _document(zac: requests.Session, zac_url: str, zaak: JsonObject, document: JsonObject) -> JsonObject:
    """ZAC's view of the zaak's document."""
    response = zac.get(document_url(zac_url, document), params={"zaak": str(zaak["uuid"])})
    return cast("JsonObject", expect_status(response, HTTPStatus.OK).json())


def _status(zac: requests.Session, zac_url: str, zaak: JsonObject) -> object:
    """The omschrijving of the zaak's status in ZAC."""
    return section(read_zaak(zac, zac_url, str(zaak["uuid"])), "status").get("naam")


@ZAC_TEAM
@THROWAWAY
@TAKEN_ZAAKTYPE
@pytest.mark.scenario("""
    Given a zaak in behandeling in ZAC, of a zaaktype with every human task on
    Then ZAC offers the taken Goedkeuren, Advies intern, Advies extern and Document verzenden
    When the behandelaar starts Advies intern with a vraag and a toelichting
    Then the taak keeps both and is in Mijn taken, and the zaak cannot be afgehandeld
    When the behandelaar completes the taak with an advies
    Then the taak is afgerond with that advies and leaves Mijn taken
    And the zaak can be afgehandeld
""")
def test_open_advies_intern_holds_off_afhandelen(
    zac: requests.Session, urls: dict[str, str], behandeling: JsonObject, zac_group: str
) -> None:
    """The stage In behandeling offers the four human tasks; ZAAK_AFHANDELEN waits until the open one is afgerond."""
    zac_url = urls["zac"]
    offered = wait_until(
        lambda: {str(item.get("naam")) for item in human_tasks_offered(zac, zac_url, behandeling)} or None,
        timeout=LIST_TIMEOUT,
        description=f"human tasks on {behandeling['identificatie']}",
    )
    assert offered == {GOEDKEUREN, ADVIES_INTERN, ADVIES_EXTERN, DOCUMENT_VERZENDEN}
    taak = _started(
        zac, zac_url, behandeling, ADVIES_INTERN, zac_group, toelichting=TOELICHTING, taakdata={"vraag": VRAAG}
    )
    assert (taak.get("toelichting"), section(taak, "taakdata").get("vraag")) == (TOELICHTING, VRAAG)
    assert "ZAAK_AFHANDELEN" not in _acties(zac, zac_url, behandeling)
    wait_until(
        lambda: is_taak_listed(zac, zac_url, taak, alleenMijnTaken=True),
        timeout=LIST_TIMEOUT,
        description=f"task {taak['id']} listed",
    )

    afgerond = complete_task(zac, zac_url, taak, {"advies": ADVIES})
    assert (afgerond.get("status"), section(afgerond, "taakdata").get("advies")) == ("AFGEROND", ADVIES)
    wait_until(
        lambda: not is_taak_listed(zac, zac_url, taak, alleenMijnTaken=True),
        timeout=LIST_TIMEOUT,
        description=f"task {taak['id']} gone",
    )
    assert "ZAAK_AFHANDELEN" in _acties(zac, zac_url, behandeling)


@pytest.mark.xfail(
    strict=True,
    reason="[zac-12] ZAC 5.9.1 does not store the referentietabel of human task parameters on their first save, so "
    "Advies intern offers no Advies values; not yet reported upstream",
)
@ZAC_TEAM
@THROWAWAY
@TAKEN_ZAAKTYPE
@pytest.mark.scenario("""
    Given a zaaktype whose human tasks the beheerder switched on in one save
    When the behandelaar starts Advies intern on a zaak in behandeling
    Then the taak offers the values of the referentietabel Advies to choose from
""")
def test_advies_intern_offers_the_advies_referentietabel(
    zac: requests.Session, urls: dict[str, str], behandeling: JsonObject, zac_group: str
) -> None:
    """The taak's tabellen hold the values of the referentietabel the human task parameters name for field ADVIES."""
    zac_url = urls["zac"]
    taak = _started(zac, zac_url, behandeling, ADVIES_INTERN, zac_group, taakdata={"vraag": VRAAG})
    wanted = referentietabel_values(referentietabel(zac, zac_url, "ADVIES"))
    assert sorted(strings(section(taak, "tabellen").get("ADVIES"))) == sorted(wanted)


@ZAC_TEAM
@THROWAWAY
@TAKEN_ZAAKTYPE
@pytest.mark.scenario("""
    Given a zaak in behandeling in ZAC with a document
    When the behandelaar starts Goedkeuren with a vraag about the document
    And completes it akkoord, ondertekenen the document
    Then the taak is afgerond and the document is ondertekend
    And a second Goedkeuren that ondertekent the same document cannot be completed
""")
def test_goedkeuren_signs_the_selected_document(
    zac: requests.Session,
    urls: dict[str, str],
    behandeling: JsonObject,
    zac_group: str,
    registry: ResourceRegistry,
) -> None:
    """Completing Goedkeuren signs the documents in taakdata ondertekenen; ZAC refuses to sign one twice."""
    zac_url = urls["zac"]
    document = uploaded_document(zac, zac_url, behandeling, registry, suffix="pdf")
    vraag = {"vraag": VRAAG, "relevanteDocumenten": str(document["uuid"])}
    akkoord = {"ondertekenen": str(document["uuid"]), "goedkeuren": "goedkeuren.AKKOORD"}
    taak = _started(zac, zac_url, behandeling, GOEDKEUREN, zac_group, taakdata=vraag)
    assert complete_task(zac, zac_url, taak, akkoord).get("status") == "AFGEROND"
    assert "ONDERTEKEND" in strings(_document(zac, zac_url, behandeling, document).get("indicaties"))

    tweede = _started(zac, zac_url, behandeling, GOEDKEUREN, zac_group, taakdata=vraag)
    body = {**tweede, "taakdata": {**section(tweede, "taakdata"), **akkoord}}
    expect_status(zac.patch(f"{zac_url}/rest/taken/complete", json=body), HTTPStatus.BAD_REQUEST)


@ZAC_TEAM
@THROWAWAY
@TAKEN_ZAAKTYPE
@pytest.mark.requires("mailpit")
@pytest.mark.scenario("""
    Given a zaak in behandeling in ZAC, whose taak Advies extern mails the adviseur
    When the behandelaar starts Advies extern with an adviseur, an e-mail address and a text
    Then the mail with that text arrives at the address
    And the zaak has the mail as a PDF
    When the behandelaar completes the taak with the extern advies
    Then the taak is afgerond with that advies
""")
def test_advies_extern_mails_the_adviseur(
    zac: requests.Session,
    urls: dict[str, str],
    behandeling: JsonObject,
    zac_group: str,
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """Starting Advies extern with sendMail mails taakdata body to emailadres and stores the mail on the zaak."""
    zac_url = urls["zac"]
    adres = own_address(registry)
    taakdata = {"adviseur": "podiumd-tests", "emailadres": adres, "body": "<p>Advies over zaak {ZAAK_NUMMER}</p>"}
    sturen = {"sendMail": True, "mail": "TAAK_ADVIES_EXTERN"}
    taak = _started(zac, zac_url, behandeling, ADVIES_EXTERN, zac_group, taakdata=taakdata, taakStuurGegevens=sturen)
    message = received_message(mailpit, registry, timeout=MAIL_TIMEOUT, to=adres)
    assert f"Advies over zaak {behandeling['identificatie']}" in str(message.get("HTML"))
    titels = [document.get("titel") for document in zaak_documents(zac, zac_url, behandeling)]
    assert message.get("Subject") in titels

    afgerond = complete_task(zac, zac_url, taak, {"externAdvies": VRAAG})
    assert (afgerond.get("status"), section(afgerond, "taakdata").get("externAdvies")) == ("AFGEROND", VRAAG)


@ZAC_TEAM
@THROWAWAY
@TAKEN_ZAAKTYPE
@pytest.mark.scenario("""
    Given a zaak in behandeling in ZAC with a definitief PDF
    When the behandelaar starts Document verzenden for the PDF
    And completes the taak with yesterday as verzenddatum
    Then the document has yesterday as verzenddatum and shows as verzonden
""")
def test_document_verzenden_records_the_verzenddatum(
    zac: requests.Session,
    urls: dict[str, str],
    behandeling: JsonObject,
    zac_group: str,
    registry: ResourceRegistry,
) -> None:
    """Completing Document verzenden sets the verzenddatum of the documents in taakdata documentenVerzendenPost."""
    zac_url = urls["zac"]
    document = uploaded_document(zac, zac_url, behandeling, registry, suffix="pdf")
    taakdata = {"documentenVerzendenPost": str(document["uuid"]), "toelichting": TOELICHTING}
    taak = _started(zac, zac_url, behandeling, DOCUMENT_VERZENDEN, zac_group, taakdata=taakdata)
    gisteren = date.today() - timedelta(days=1)  # noqa: DTZ011  # ZAC's local date
    # ZAC parses the verzenddatum its UI sends: a date and time with offset.
    afgerond = complete_task(zac, zac_url, taak, {"verzenddatum": f"{gisteren}T12:00:00+01:00"})
    assert afgerond.get("status") == "AFGEROND"
    verzonden = _document(zac, zac_url, behandeling, document)
    assert verzonden.get("verzenddatum") == gisteren.isoformat()
    assert "VERZONDEN" in strings(verzonden.get("indicaties"))


@ZAC_TEAM
@THROWAWAY
@TAKEN_ZAAKTYPE
@pytest.mark.scenario("""
    Given a zaak in behandeling in ZAC, whose taak Goedkeuren takes longer than the zaak has left
    When the behandelaar starts Goedkeuren with a fatale datum after the zaak's
    Then ZAC refuses it
    When the behandelaar starts Goedkeuren without a fatale datum
    Then the taak's fatale datum is the zaak's
""")
def test_taak_fatale_datum_stays_within_the_zaaks(
    zac: requests.Session,
    urls: dict[str, str],
    behandeling: JsonObject,
    zac_group: str,
    zac_taken_zaaktype: JsonObject,
) -> None:
    """A later fatale datum is refused; the doorlooptijd of the human task parameters is capped at the zaak's."""
    zac_url = urls["zac"]
    einde = date.fromisoformat(str(behandeling["uiterlijkeEinddatumAfdoening"]))
    goedkeuren = next(
        task
        for task in entries(zac_taken_zaaktype.get("humanTaskParameters"))
        if section(task, "planItemDefinition").get("id") == "GOEDKEUREN"
    )
    assert date.today() + timedelta(days=int(str(goedkeuren["doorlooptijd"]))) > einde  # noqa: DTZ011  # a local date
    later = (einde + timedelta(days=1)).isoformat()
    refused = start_human_task(zac, zac_url, behandeling, GOEDKEUREN, zac_group, fataledatum=later)
    expect_status(refused, HTTPStatus.BAD_REQUEST)
    taak = _started(zac, zac_url, behandeling, GOEDKEUREN, zac_group, taakdata={"vraag": VRAAG})
    assert taak.get("fataledatum") == einde.isoformat()


@ZAC_TEAM
@THROWAWAY
@TAKEN_ZAAKTYPE
@pytest.mark.requires("mailpit")
@pytest.mark.parametrize(
    "uitkomst",
    [
        "aanvullende-informatie.geleverd-akkoord",
        "aanvullende-informatie.geleverd-niet-akkoord",
        "aanvullende-informatie.niet-geleverd",
    ],
)
@pytest.mark.scenario("""
    Given a zaak in its intake in ZAC
    When the behandelaar starts Aanvullende informatie with a mail to an e-mail address
    Then the mail arrives, and the zaak has it as a PDF
    And the zaak has the status Wacht op aanvullende informatie
    When the behandelaar completes the taak with an uitkomst
    Then the taak is afgerond with that uitkomst, and the zaak has the status Intake again
""")
def test_aanvullende_informatie_mails_and_returns_the_zaak_to_intake(
    zac: requests.Session,
    urls: dict[str, str],
    zac_taken_zaak: Callable[[], JsonObject],
    zac_group: str,
    mailpit: ApiClient,
    registry: ResourceRegistry,
    uitkomst: str,
) -> None:
    """Aanvullende informatie with sendMail mails and stores the mail; completing it gives back the status Intake."""
    zac_url = urls["zac"]
    zaak = zac_taken_zaak()
    adres = own_address(registry)
    taakdata = {"emailadres": adres, "body": "<p>Graag meer over zaak {ZAAK_NUMMER}</p>"}
    sturen = {"sendMail": True, "mail": "TAAK_AANVULLENDE_INFORMATIE"}
    taak = _started(zac, zac_url, zaak, AANVULLENDE_INFORMATIE, zac_group, taakdata=taakdata, taakStuurGegevens=sturen)
    message = received_message(mailpit, registry, timeout=MAIL_TIMEOUT, to=adres)
    assert f"Graag meer over zaak {zaak['identificatie']}" in str(message.get("HTML"))
    titels = [document.get("titel") for document in zaak_documents(zac, zac_url, zaak)]
    assert titels.count(message.get("Subject")) == 1
    assert _status(zac, zac_url, zaak) == WAITING

    afgerond = complete_task(zac, zac_url, taak, {"aanvullendeInformatie": uitkomst})
    assert section(afgerond, "taakdata").get("aanvullendeInformatie") == uitkomst
    assert _status(zac, zac_url, zaak) == INTAKE
