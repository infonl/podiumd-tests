"""ZAC's CMMN human tasks that mail: Advies extern and Aanvullende informatie, and the mail they keep on the zaak.

The mails go to run-tagged addresses at Mailpit; cleanup deletes them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.json_data import section
from podiumd_tests.mailpit import own_address
from podiumd_tests.mailpit import received_message
from podiumd_tests.pdf import pdfa_problems
from podiumd_tests.responses import get_entries
from podiumd_tests.zac import zaak_status
from podiumd_tests.zac_documents import stored_mail
from podiumd_tests.zac_documents import zaak_documents
from podiumd_tests.zac_taken import AANVULLENDE_INFORMATIE
from podiumd_tests.zac_taken import ADVIES_EXTERN
from podiumd_tests.zac_taken import complete_task
from podiumd_tests.zac_taken import started_taak

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "openzaak", "keycloak")]

ZAC_TEAM = pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, taken-cmmn).",
)
# Fixture zac_taken_zaaktype: a throwaway zaaktype made known to PABC and deleted with a Django snippet, one per run.
THROWAWAY = pytest.mark.requires("pabc", "cluster")
TAKEN_ZAAKTYPE = pytest.mark.xdist_group("zac-taken-zaaktype")
# ZAC's statustype omschrijvingen while a task Aanvullende informatie is open, and after (ConfigurationService).
WAITING = "Wacht op aanvullende informatie"
INTAKE = "Intake"
VRAAG = "podiumd-tests vraag"
MAIL_TIMEOUT = 60


# A taak mail on its zaak: ZAC offers no vertrouwelijkheidaanduiding for it (PlanItemsRestService).
STORED_MAIL = ("definitief", "OPENBAAR", [])


def _stored(zac: requests.Session, zac_url: str, zaak: JsonObject, message: JsonObject) -> tuple[object, ...]:
    """Status, vertrouwelijkheidaanduiding and PDF/A problems of the zaak's document of the mail."""
    stored, pdf = stored_mail(zac, zac_url, zaak, message)
    return stored.get("status"), stored.get("vertrouwelijkheidaanduiding"), pdfa_problems(pdf)


@ZAC_TEAM
@THROWAWAY
@TAKEN_ZAAKTYPE
@pytest.mark.requires("mailpit")
@pytest.mark.scenario("""
    Given a zaak in behandeling in ZAC, whose taak Advies extern mails the adviseur
    When the behandelaar starts Advies extern with an adviseur, an e-mail address and a text
    Then the mail with that text arrives at the address
    And the zaak has the mail as a definitief, openbaar PDF/A
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
    taak = started_taak(
        zac,
        zac_url,
        behandeling,
        ADVIES_EXTERN,
        (zac_group, ADMIN.username),
        taakdata=taakdata,
        taakStuurGegevens=sturen,
    )
    message = received_message(mailpit, registry, timeout=MAIL_TIMEOUT, to=adres)
    assert f"Advies over zaak {behandeling['identificatie']}" in str(message.get("HTML"))
    assert _stored(zac, zac_url, behandeling, message) == STORED_MAIL

    afgerond = complete_task(zac, zac_url, taak, {"externAdvies": VRAAG})
    assert (afgerond.get("status"), section(afgerond, "taakdata").get("externAdvies")) == ("AFGEROND", VRAAG)


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
    Then the mail arrives, and the zaak has it as a definitief, openbaar PDF/A
    And the zaak has the status Wacht op aanvullende informatie
    When the behandelaar completes the taak with an uitkomst
    Then the taak is afgerond with that uitkomst, and the zaak has the status Intake again
    When the behandelaar starts Aanvullende informatie with a mail again
    Then that mail arrives, and the zaak has one more PDF and one open taak
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

    def mailed() -> tuple[JsonObject, JsonObject]:
        adres = own_address(registry)
        taakdata = {"emailadres": adres, "body": "<p>Graag meer over zaak {ZAAK_NUMMER}</p>"}
        sturen = {"sendMail": True, "mail": "TAAK_AANVULLENDE_INFORMATIE"}
        started = started_taak(
            zac,
            zac_url,
            zaak,
            AANVULLENDE_INFORMATIE,
            (zac_group, ADMIN.username),
            taakdata=taakdata,
            taakStuurGegevens=sturen,
        )
        message = received_message(mailpit, registry, timeout=MAIL_TIMEOUT, to=adres)
        assert f"Graag meer over zaak {zaak['identificatie']}" in str(message.get("HTML"))
        return started, message

    def pdfs(message: JsonObject) -> int:
        return [document.get("titel") for document in zaak_documents(zac, zac_url, zaak)].count(message.get("Subject"))

    taak, message = mailed()
    assert pdfs(message) == 1
    assert _stored(zac, zac_url, zaak, message) == STORED_MAIL
    assert zaak_status(zac, zac_url, zaak) == WAITING

    afgerond = complete_task(zac, zac_url, taak, {"aanvullendeInformatie": uitkomst})
    assert section(afgerond, "taakdata").get("aanvullendeInformatie") == uitkomst
    assert zaak_status(zac, zac_url, zaak) == INTAKE

    _, message = mailed()
    assert pdfs(message) == 2
    taken = get_entries(zac, f"{zac_url}/rest/taken/zaak/{zaak['uuid']}")
    assert sorted(str(item.get("status")) for item in taken) == sorted(["AFGEROND", str(taak.get("status"))]), taken
