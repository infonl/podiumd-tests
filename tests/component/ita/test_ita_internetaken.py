"""ITA as the klantcontactmedewerker: lists, claiming an internetaak and answering it with a klantcontact.

Ported from TA regression 77, 73 and interaction 74 and 180 (with a numeric nummer and the
current add-klantcontact body; the TA versions failed on both). Claiming and answering write
ITA's logboek to Objecten, which needs an edge that buffers request bodies, as nginx does;
KISS reads that logboek with its own Objecten token.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ITA_GROEP
from podiumd_tests.clients.platform import mailpit_client
from podiumd_tests.clients.platform import objecten_client
from podiumd_tests.ita import answer_body
from podiumd_tests.ita import assign_to_me
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kcc import add_klantcontact
from podiumd_tests.kcc import expect_ita_group_access_bug
from podiumd_tests.kcc import ita_afhandeltermijn_hours
from podiumd_tests.kcc import ita_bijna_verlopen_hours
from podiumd_tests.kcc import weekday_hours_before
from podiumd_tests.mailpit import received
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.results import TAG_PREFIX
from podiumd_tests.seed.objecten import clean_up_logboek
from podiumd_tests.seed.objecten import make_object
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openklant import clean_up_klantcontacten
from podiumd_tests.seed.openklant import close_internetaak
from podiumd_tests.seed.openklant import klantcontact_body
from podiumd_tests.seed.openklant import klantcontacten_about
from podiumd_tests.seed.openklant import make_actor
from podiumd_tests.seed.openklant import make_internetaak
from podiumd_tests.seed.openklant import make_klantcontact
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.requires("ita", "openklant", "keycloak")]

ITA_E2E = "upstream interne-taak-afhandeling/ITA InterneTaakAfhandeling.EndToEndTest"
# ITA sends its mail in the request; Mailpit lists it within seconds.
MAIL_TIMEOUT = 60
# A klantcontact nummer Open Klant never hands out (its numbers come from random_nummer).
UNKNOWN_NUMMER = "0000000000"


@pytest.mark.source(
    "TA regression/77-ita-afdelingen-groepen.spec.ts",
    "Checks ITA's afdelingen and groepen answer, and catches a seed that fills only one of them.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    When the medewerker lists ITA's afdelingen and groepen
    Then both lists answer
    And both are empty or both are filled
""")
def test_afdelingen_and_groepen_are_seeded_together(ita: requests.Session, urls: dict[str, str]) -> None:
    """Afdelingen and groepen both answer, and are both empty or both filled (TA reg-77)."""

    def seeded(path: str) -> list[JsonObject]:
        # Other tests of the run create their own afdeling or groep (ptest-<run>-...) at the same time.
        return [e for e in get_entries(ita, urls["ita"] + path) if not str(e.get("naam")).startswith(TAG_PREFIX)]

    afdelingen, groepen = seeded("/api/afdelingen"), seeded("/api/groepen")
    assert bool(afdelingen) == bool(groepen), f"{len(afdelingen)} afdelingen, {len(groepen)} groepen"


@pytest.mark.tc("ITA-024")
@pytest.mark.source(
    "TA interaction/74-ita-claim-flow.spec.ts",
    "Checks a KCC employee can claim an open internetaak in ITA, which assigns it to their own actor.",
)
@pytest.mark.source(
    "TA regression/73-ita-assigned-list.spec.ts",
    "Checks ITA's assigned-to-me list, the werkbak where a KCC employee sees their daily work.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    And an unassigned contactverzoek in Open Klant
    When the medewerker claims it in ITA
    Then the contactverzoek is assigned in Open Klant
    And it is on the medewerker's own list in ITA
""")
def test_claimed_internetaak_is_on_my_list(
    ita: requests.Session, urls: dict[str, str], openklant: ApiClient, internetaak: JsonObject
) -> None:
    """A claimed internetaak is assigned to the user's actor and on the user's list (TA int-74, reg-73)."""
    assign_to_me(ita, urls["ita"], internetaak)
    assert entries(openklant.get(f"internetaken/{internetaak['uuid']}")["toegewezenAanActoren"])
    mine = get_entries(ita, f"{urls['ita']}/api/internetaken/aan-mij-toegewezen")
    assert internetaak["uuid"] in {str(t.get("uuid")) for t in mine}


@pytest.mark.parametrize("gelukt", [False, True], ids=["niet gelukt", "gelukt"])
@pytest.mark.source(
    "TA interaction/180-ita-contactmoment-afsluiten.spec.ts",
    "Checks a KCC employee can register a contactmoment on an internetaak in ITA and close it.",
)
@pytest.mark.source(
    f"{ITA_E2E}/Contactverzoek/ContactverzoekScenarios.cs",
    "A contactmoment, gelukt or not, is registered without closing the contactverzoek.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    And an unassigned contactverzoek in Open Klant
    When the medewerker registers a contact in ITA that did or did not succeed, without closing
    Then that klantcontact is in Open Klant, marked gelukt or not gelukt
    And the contactverzoek stays te_verwerken
""")
def test_answering_an_internetaak_registers_a_klantcontact(
    ita: requests.Session,
    urls: dict[str, str],
    openklant: ApiClient,
    registry: ResourceRegistry,
    internetaak: JsonObject,
    gelukt: bool,  # noqa: FBT001  # a parameter
) -> None:
    """A contactmoment on an internetaak is a klantcontact in Open Klant; the internetaak stays open (TA int-180)."""
    onderwerp = registry.tagged("ita-antwoord")
    clean_up_klantcontacten(openklant, registry, onderwerp)
    antwoord = klantcontact_body(registry, onderwerp=onderwerp, indicatieContactGelukt=gelukt)
    add_klantcontact(ita, urls["ita"], answer_body(internetaak, antwoord))
    assert [k["indicatieContactGelukt"] for k in klantcontacten_about(openklant, onderwerp)] == [gelukt]
    assert openklant.get(f"internetaken/{internetaak['uuid']}")["status"] == "te_verwerken"


@pytest.mark.source(
    "TA smoke/72-ita-health-kanalen.spec.ts",
    "Checks ITA's kanalen endpoint answers and enforces login; without it no KCC employee can use ITA.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    When the medewerker asks ITA for its kanalen
    Then ITA answers with a list of kanalen
""")
def test_kanalen_answer_the_kcc_user(ita: requests.Session, urls: dict[str, str]) -> None:
    """With a login, ITA lists its kanalen (TA smoke 72; anonymous it refuses, test_api_health)."""
    assert isinstance(expect_status(ita.get(f"{urls['ita']}/api/kanalen"), HTTPStatus.OK).json(), list)


@pytest.mark.parametrize("soort", ["Afdeling", "Groep"])
@pytest.mark.source(
    "TA regression/184-ita-doorsturen-mutatie.spec.ts",
    "Checks forwarding a contactverzoek in ITA to an afdeling or a groep assigns it there.",
)
@pytest.mark.source(
    f"{ITA_E2E}/Contactverzoek/ContactverzoekDoorsturenGroepsmailboxScenarios.cs",
    "An afdeling or groep with a groepsmailbox gets the forwarded contactverzoek by mail.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    And a contactverzoek, and an afdeling or groep with a groepsmailbox
    When the medewerker forwards the contactverzoek to the afdeling or groep
    Then the contactverzoek is assigned to it in Open Klant
    And its groepsmailbox gets the mail "Contactverzoek Doorgestuurd" with the klantcontact's nummer, where mail is tested
""")
def test_forwarded_internetaak_is_assigned_to_the_afdeling_or_groep(
    ita: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    internetaak: JsonObject,
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
    forward = ita.post(
        f"{urls['ita']}/api/internetaken/{internetaak['uuid']}/forward", json={soort.lower(): identificatie}
    )
    expect_status(forward, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assigned = entries(openklant.get(f"internetaken/{internetaak['uuid']}")["toegewezenAanActoren"])
    assert {str(a["uuid"]) for a in assigned} & {str(a["uuid"]) for a in openklant.list("actoren", actoren)}
    if podiumd_env.capabilities.skip_reason("mailpit") is None:
        # ITA mails the afdeling's or groep's mailbox about the forwarded contactverzoek.
        nummer = openklant.get(str(section(internetaak, "aanleidinggevendKlantcontact")["url"]))["nummer"]
        subject = f"Contactverzoek Doorgestuurd - {nummer}"
        received(mailpit_client(podiumd_env), registry, timeout=MAIL_TIMEOUT, to=data["email"], subject=subject)


@pytest.mark.requires("kiss", "objecten", "cluster")
# Non-strict: an estate setting; environments with helm-charts #684's permission (minikube, kees00) pass.
@pytest.mark.xfail(
    strict=False,
    reason="[kiss-2] reference configuration (ExternalsPodiumD, podiumd-infra): KISS's Objecten token"
    " (LOGBOEK_TOKEN) has no permission on Activiteitenlog, only ITA's has; Objecten answers 200 with"
    " an empty list, so KISS shows none of ITA's activities; fix: helm-charts #684 migrate script",
)
@pytest.mark.source(
    "podiumd-tests",
    "KISS reads the Activiteitenlog entries ITA writes with its own Objecten token, so that token needs read access.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    When the medewerker claims a contactverzoek in ITA
    Then ITA writes an entry in its logboek in Objecten
    And KISS reads the same entries with its own Objecten token
""")
def test_kiss_reads_itas_logboek(
    ita: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    objecten: ApiClient,
    logboek_type: str,
    internetaak: JsonObject,
) -> None:
    """The logboek entry ITA writes when claiming an internetaak is visible with KISS's logboek token."""
    if not podiumd_env.credentials.is_configured("kiss_logboek_token"):
        pytest.skip(f"profile {podiumd_env.profile.name} has no secret kiss_logboek_token")
    assign_to_me(ita, urls["ita"], internetaak)
    query = {"type": logboek_type, "data_attr": f"heeftBetrekkingOp__objectId__exact__{internetaak['uuid']}"}
    written = wait_until(lambda: objecten.list("objects", query), timeout=30, description="ITA's logboek entry")
    kiss = objecten_client(podiumd_env, "kiss_logboek_token")
    assert [o["url"] for o in kiss.list("objects", query)] == [o["url"] for o in written]


@pytest.mark.source(
    f"{ITA_E2E}/Contactverzoek/ContactverzoekDoorsturenGroepsmailboxScenarios.cs",
    "Forwarding to an afdeling without groepsmailbox and without medewerker is refused.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    And a contactverzoek, and an afdeling without e-mail address
    When the medewerker forwards it to the afdeling without choosing a medewerker
    Then ITA refuses it
    And the contactverzoek stays unassigned in Open Klant
""")
def test_forward_to_an_afdeling_without_mailbox_is_refused(
    ita: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    internetaak: JsonObject,
) -> None:
    """ITA refuses to forward to an afdeling that has no e-mail address when no medewerker is chosen; nothing changes."""
    identificatie = registry.tagged("afdeling")
    make_object(
        objecten,
        registry,
        objecttype_url(podiumd_env, "Afdeling"),
        {"naam": identificatie, "identificatie": identificatie},
    )
    registry.add(
        f"actoren of {identificatie}",
        lambda: [
            openklant.delete(str(a["url"]))
            for a in openklant.list("actoren", {"actoridentificatorObjectId": identificatie})
        ],
    )
    forward = ita.post(
        f"{urls['ita']}/api/internetaken/{internetaak['uuid']}/forward", json={"afdeling": identificatie}
    )
    expect_status(forward, HTTPStatus.BAD_REQUEST)
    assert entries(openklant.get(f"internetaken/{internetaak['uuid']}")["toegewezenAanActoren"]) == []


@pytest.mark.source(
    f"{ITA_E2E}/Contactverzoek/KlantcontactZoekenScenarios.cs",
    "A medewerker finds a contactverzoek by its klantcontact number; not one outside their rights, nor an unknown one.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    When the medewerker searches a contactverzoek by its klantcontact's nummer
    Then ITA finds one assigned to the medewerker's groep
    And refuses one outside the medewerker's afdelingen and groepen
    And answers 404 to an unknown nummer
""")
def test_contactverzoek_is_found_by_its_klantcontactnummer(
    ita: requests.Session,
    urls: dict[str, str],
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    logboek_type: str,
    need_bootstrap: Callable[..., None],
    request: pytest.FixtureRequest,
    podiumd_env: Environment,
) -> None:
    """ITA finds a contactverzoek of the user's groep by its klantcontact's nummer; not one outside the user's groepen.

    ITA shows a medewerker only contactverzoeken assigned to one of their afdelingen or groepen (403), and answers
    404 to an unknown nummer.
    """
    expect_ita_group_access_bug(request, podiumd_env)
    need_bootstrap("objecten-medewerker-kcc")

    def nummer_of(actoren: list[JsonObject]) -> str:
        klantcontact = make_klantcontact(openklant, registry)
        taak = make_internetaak(openklant, registry, klantcontact, actoren)
        clean_up_logboek(objecten, registry, logboek_type, str(taak["uuid"]))
        return str(klantcontact["nummer"])

    by_nummer = f"{urls['ita']}/api/internetaken/by-klantcontact"
    mine = nummer_of([make_actor(openklant, registry, "organisatorische_eenheid", ITA_GROEP, "grp")])
    assert str(expect_status(ita.get(f"{by_nummer}/{mine}"), HTTPStatus.OK).json()["aanleidinggevendKlantcontact"])
    expect_status(ita.get(f"{by_nummer}/{nummer_of([])}"), HTTPStatus.FORBIDDEN)
    expect_status(ita.get(f"{by_nummer}/{UNKNOWN_NUMMER}"), HTTPStatus.NOT_FOUND)


type _Call = tuple[str, dict[str, object]]


def _guarded_calls(taak: JsonObject) -> dict[str, _Call]:
    """ITA's writes on one contactverzoek: path and the smallest body its model accepts."""
    uuid = str(taak["uuid"])
    klantcontact = str(section(taak, "aanleidinggevendKlantcontact").get("uuid"))
    return {
        "assign to self": (f"/api/internetaken/{uuid}/aan-mij-toewijzen", {}),
        "notitie": (f"/api/internetaken/{uuid}/notitie", {"notitie": "podiumd-tests"}),
        "forward": (f"/api/internetaken/{uuid}/forward", {"afdeling": "podiumd-tests"}),
        "link a zaak": (
            "/api/internetaken/koppel-zaak",
            {
                "internetaakId": uuid,
                "zaakIdentificatie": "ZAAK-PTEST",
                "aanleidinggevendKlantcontactUuid": klantcontact,
            },
        ),
        "register a contactmoment": (
            "/api/internetaken/close-with-klantcontact",
            answer_body(
                taak,
                {
                    "indicatieContactGelukt": True,
                    "onderwerp": "podiumd-tests",
                    "inhoud": "podiumd-tests",
                    "kanaal": "e-mail",
                    "taal": "nl",
                    "vertrouwelijk": False,
                },
            ),
        ),
    }


@pytest.mark.parametrize("action", ["assign to self", "notitie", "forward", "link a zaak", "register a contactmoment"])
@pytest.mark.source(
    f"{ITA_E2E}/Contactverzoek/ContactverzoekScenarios.cs",
    "A verwerkt contactverzoek is read-only: assigning, a notitie, forwarding, a zaak link and a contactmoment get 409.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    And a contactverzoek in Open Klant that is verwerkt
    When the medewerker changes it in ITA
    Then ITA refuses with a conflict that names the status verwerkt
    And the contactverzoek stays verwerkt in Open Klant
""")
def test_a_verwerkt_contactverzoek_is_read_only(
    ita: requests.Session, urls: dict[str, str], openklant: ApiClient, internetaak: JsonObject, action: str
) -> None:
    """Each write ITA offers on a contactverzoek answers 409 naming verwerkt once Open Klant has it verwerkt."""
    close_internetaak(openklant, internetaak)
    path, body = _guarded_calls(internetaak)[action]
    refused = expect_status(ita.post(urls["ita"] + path, json=body), HTTPStatus.CONFLICT)
    assert "verwerkt" in refused.text, refused.text[:300]
    assert openklant.get(f"internetaken/{internetaak['uuid']}")["status"] == "verwerkt"


@pytest.mark.source(
    f"{ITA_E2E}/Werklijst/WerklijstUrgentieScenarios.cs",
    "The werklijst marks each contactverzoek in time, almost overdue or overdue, counting weekday hours only.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker has claimed three contactverzoeken in ITA
    And their klantcontacten took place now, just inside the afhandeltermijn and long before it
    When the medewerker opens the contactverzoeken assigned to them
    Then ITA marks them in time, almost overdue and overdue
    And weekends do not count towards the afhandeltermijn
""")
def test_werklijst_shows_the_urgency_of_each_contactverzoek(
    podiumd_env: Environment,
    ita: requests.Session,
    urls: dict[str, str],
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    logboek_type: str,
) -> None:
    """ITA's urgentie status per contactverzoek in Aan mij toegewezen: success, warning or error (weekday hours)."""
    termijn, bijna = ita_afhandeltermijn_hours(podiumd_env), ita_bijna_verlopen_hours(podiumd_env)
    now = datetime.now(tz=UTC)
    ages = {"success": 0, "warning": termijn - bijna / 2, "error": termijn + 24}
    expected: dict[str, str] = {}
    for status, hours in ages.items():
        plaatsgevonden = weekday_hours_before(now, hours).isoformat()
        taak = make_internetaak(
            openklant, registry, make_klantcontact(openklant, registry, plaatsgevondenOp=plaatsgevonden), []
        )
        clean_up_logboek(objecten, registry, logboek_type, str(taak["uuid"]))
        assign_to_me(ita, urls["ita"], taak)
        expected[str(taak["uuid"])] = status
    mine = {str(t.get("uuid")): t for t in get_entries(ita, f"{urls['ita']}/api/internetaken/aan-mij-toegewezen")}
    found = {uuid: section(mine.get(uuid, {}), "urgentie").get("status") for uuid in expected}
    assert found == expected, {uuid: mine.get(uuid, {}).get("urgentie") for uuid in expected}
