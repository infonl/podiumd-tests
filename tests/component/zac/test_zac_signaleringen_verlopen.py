"""ZAC's expiry signaleringen for overdue taken and for zaken nearing their streefdatum or fatale datum, mailed by
ZAC's signaleringen job.

The job (CronJob <release>-signaleren, weekdays) mails every assignee who turned the mail on, for every overdue taak
of the environment: destructive, and only where Mailpit catches the mail. It stores no dashboard signal. For zaken it
reads only the zaaktypen of ZAC's own catalogus with a waarschuwingsvenster.
"""

from __future__ import annotations

import secrets

from datetime import date
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.keycloak_admin import user_email
from podiumd_tests.bootstrap.bpmn import INTAKE
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.mailpit import quoted
from podiumd_tests.mailpit import received_mails
from podiumd_tests.seed.openzaak import today
from podiumd_tests.seed.zac_zaaktype import make_group_member
from podiumd_tests.seed.zac_zaaktype import make_role_group
from podiumd_tests.seed.zac_zaaktype import make_zac_zaaktype
from podiumd_tests.seed.zac_zaaktype import zac_as_admin
from podiumd_tests.workloads import cronjob_ending
from podiumd_tests.workloads import run_cronjob
from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import forget_zaak_at_cleanup
from podiumd_tests.zac import save_zaakafhandelparameters
from podiumd_tests.zac import zac_session
from podiumd_tests.zac_signaleringen import signalering_mail
from podiumd_tests.zac_signaleringen import turn_signaleringen
from podiumd_tests.zac_taken import open_task
from podiumd_tests.zac_taken import toekennen_taak
from podiumd_tests.zac_taken import wijzig_taak

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.destructive,
    pytest.mark.requires("zac", "openzaak", "keycloak", "mailpit", "cluster"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md,"
        " zoeken-werklijsten-dashboard): signaleringen.",
    ),
]

# The ZAC chart's CronJob that calls /rest/internal/signaleringen/send-signaleringen.
SIGNALEREN = "-signaleren"
# The job answers at once and sends in the background.
MAIL_TIMEOUT = 120


@pytest.fixture(name="signaleren")
def fixture_signaleren(podiumd_env: Environment, registry: ResourceRegistry) -> Callable[[], None]:
    """Return a run of ZAC's signaleringen job, once now."""
    cronjob = cronjob_ending(podiumd_env, SIGNALEREN)
    if cronjob is None:
        pytest.skip(f"ZAC has no CronJob *{SIGNALEREN} here")
    return lambda: run_cronjob(podiumd_env.kube, cronjob, registry.tagged(f"signaleren-{secrets.token_hex(3)}"))


@pytest.mark.parametrize("days", [-1, 0], ids=["overdue", "due-today"])
@pytest.mark.scenario("""
    Given the test admin wants a mail for their taken that are overdue
    And the intake taak of a zaak is on the admin's name with a fatale datum of yesterday or today
    When ZAC's signaleringen job runs
    Then the admin gets a mail naming the zaaknummer and the zaak's omschrijving
""")
def test_overdue_taak_gives_a_mail(
    zac: requests.Session,
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_group: str,
    signaleringen: Callable[..., None],
    signaleren: Callable[[], None],
    mailpit: ApiClient,
    registry: ResourceRegistry,
    days: int,
) -> None:
    """TAAK_VERLOPEN mails the assignee of an open taak due before tomorrow, with ZAAK_OMSCHRIJVING filled in."""
    signaleringen(mail=True, TAAK_VERLOPEN=False)
    taak = open_task(zac, urls["zac"], str(bpmn_zaak["uuid"]), INTAKE)
    toekennen_taak(zac, urls["zac"], taak, zac_group, ADMIN.username)
    wijzig_taak(
        zac, urls["zac"], str(taak["id"]), fataledatum=(date.fromisoformat(today()) + timedelta(days=days)).isoformat()
    )
    signaleren()
    mail = signalering_mail(mailpit, registry, ADMIN.username, str(bpmn_zaak["identificatie"]), timeout=MAIL_TIMEOUT)
    assert str(bpmn_zaak["omschrijving"]) in str(mail.get("HTML"))


# A zaak's dates and the waarschuwingsvenster of each in the zaakafhandelparameters.
VENSTERS = {
    "einddatumGepland": "einddatumGeplandWaarschuwing",
    "uiterlijkeEinddatumAfdoening": "uiterlijkeEinddatumAfdoeningWaarschuwing",
}


@pytest.mark.xfail(
    strict=True,
    reason="[zac-35] ZAC 5.9.1's signaleringen job searches Solr as the functionele gebruiker, whom PABC grants no "
    "zaaktype, so it finds no zaak and sends no zaak verloopt bijna mail; not yet reported upstream",
)
@pytest.mark.requires("pabc")
@pytest.mark.scenario("""
    Given a zaaktype in ZAC's own catalogus with a servicenorm and a doorlooptijd
    And a behandelaar who wants a mail for zaken about to expire, with a zaak of it on their name
    And waarschuwingsvensters that reach the zaak's streefdatum and fatale datum
    When ZAC's signaleringen job runs
    Then the behandelaar gets a mail naming the streefdatum and one naming the fatale datum of the zaak
""")
def test_zaak_verloopt_bijna_gives_a_mail(
    podiumd_env: Environment,
    openzaak: ApiClient,
    test_zaaktype: JsonObject,
    eigen_catalogus: JsonObject,
    urls: dict[str, str],
    signaleren: Callable[[], None],
    mailpit: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """ZAAK_VERLOPEND mails the behandelaar of an open zaak once per date inside the zaaktype's venster."""
    need_bootstrap("zac-bpmn-process")
    parameters = make_zac_zaaktype(
        podiumd_env, openzaak, registry, test_zaaktype, catalogus=eigen_catalogus["url"], servicenorm="P10D"
    )
    group = make_role_group(podiumd_env, registry, "behandelaar")
    username, password = make_group_member(podiumd_env, registry, group)
    zac_url = urls["zac"]
    turn_signaleringen(zac_session(podiumd_env, username, password), zac_url, registry, mail=True, ZAAK_VERLOPEND=False)
    # A login after make_zac_zaaktype: ZAC reads the rights on the zaaktype from PABC at login.
    zac = zac_as_admin(podiumd_env)
    zaak = create_zaak(
        zac,
        zac_url,
        parameters,
        omschrijving=registry.tagged("zac-verloopt"),
        groep={"id": group, "naam": group},
        behandelaar={"id": username},
    )
    forget_zaak_at_cleanup(podiumd_env, registry, zaak)
    dates = {veld: date.fromisoformat(str(zaak[veld])) for veld in VENSTERS}
    start = date.fromisoformat(str(zaak["startdatum"]))
    vensters = {venster: (dates[veld] - start).days for veld, venster in VENSTERS.items()}
    saved = save_zaakafhandelparameters(zac, zac_url, {**parameters, **vensters})
    # ZAC keeps the zaakafhandelparameters of a deleted zaaktype.
    registry.add(
        "ZAC waarschuwingsvensters",
        lambda: save_zaakafhandelparameters(zac_as_admin(podiumd_env), zac_url, {**saved, **dict.fromkeys(vensters)}),
    )

    signaleren()
    query = f"to:{quoted(user_email(username))} {quoted(str(zaak['identificatie']))}"
    mails = received_mails(mailpit, registry, query, count=len(dates), timeout=MAIL_TIMEOUT)
    subjects = [str(mail.get("Subject")) for mail in mails]
    for veld, datum in dates.items():
        assert any(datum.strftime("%d-%m-%Y") in subject for subject in subjects), (veld, subjects)
