"""ZAC's expiry signalering for overdue taken, mailed by ZAC's signaleringen job.

The job (CronJob <release>-signaleren, weekdays) mails every assignee who turned the mail on, for every overdue taak
of the environment: destructive, and only where Mailpit catches the mail. It stores no dashboard signal.

Zaken nearing their streefdatum or fatale datum are left out: the job reads only the zaaktypen of ZAC's default
catalogus (CATALOGUS_DOMEIN), which are the environment's, and needs their warning days set in ZAC.
"""

from __future__ import annotations

import secrets

from datetime import date
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.bpmn import INTAKE
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.seed.openzaak import today
from podiumd_tests.workloads import cronjob_ending
from podiumd_tests.workloads import run_cronjob
from podiumd_tests.zac_signaleringen import signalering_mail
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
