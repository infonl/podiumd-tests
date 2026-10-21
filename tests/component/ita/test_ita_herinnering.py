"""ITA's daily reminder mail for overdue contactverzoeken, per afdeling.

ITA's poller (POLLER_MODE verlopen-contactverzoek-herinnering-notificatie) mails every actor with contactverzoeken
whose klantcontact took place more than 48 weekday hours ago and that are still te_verwerken. podiumd 4.10 leaves
its CronJob off (ita.verlopenContactverzoekHerinneringNotificatie.enabled, DRT-726); the test runs where an
environment turns it on. It runs the job once, which mails every overdue actor of the environment: destructive.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.kube import metadata_name
from podiumd_tests.mailpit import received
from podiumd_tests.seed.objecten import clean_up_logboek
from podiumd_tests.seed.objecten import make_object
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openklant import make_actor
from podiumd_tests.seed.openklant import make_internetaak
from podiumd_tests.seed.openklant import make_klantcontact
from podiumd_tests.workloads import run_cronjob

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.destructive,
    pytest.mark.requires("ita", "openklant", "objecten", "mailpit", "cluster"),
]

E2E = "upstream interne-taak-afhandeling/ITA InterneTaakAfhandeling.EndToEndTest/DagelijkseHerinnering"
# The chart's CronJob <release>-verlopen-cv-notify (internetaakafhandeling 3.3).
REMINDER = "-verlopen-cv-notify"
# Long past ITA's 48 weekday hours, whatever day the test runs.
OVERDUE = timedelta(days=10)
MAIL_TIMEOUT = 60


def reminder_cronjob(env: Environment) -> str:
    """The name of ITA's reminder CronJob; skips where the environment has it off."""
    found = [metadata_name(c) for c in env.items("cronjobs") if metadata_name(c).endswith(REMINDER)]
    if not found:
        pytest.skip(
            "ITA's daily reminder is off here (ita.verlopenContactverzoekHerinneringNotificatie.enabled; DRT-726)"
        )
    return found[0]


@pytest.mark.source(
    f"{E2E}/DagelijkseHerinneringScenarios.cs",
    "An afdeling gets one aggregated reminder for its overdue contactverzoeken, without personal data in the body.",
)
@pytest.mark.source(
    f"{E2E}/DagelijkseHerinneringScenarios.cs",
    "No reminder for a contactverzoek that is closed or not yet overdue; an afdeling without e-mail blocks no one.",
)
def test_afdeling_gets_one_reminder_for_its_overdue_contactverzoeken(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    podiumd_env: Environment,
    openklant: ApiClient,
    objecten: ApiClient,
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """Two overdue contactverzoeken of an afdeling give it one mail; recent, closed and mailbox-less ones give none."""
    cronjob = reminder_cronjob(podiumd_env)
    afdeling_type = objecttype_url(podiumd_env, "Afdeling")
    logboek_type = objecttype_url(podiumd_env, "Activiteitenlog")

    def afdeling(name: str, *, email: bool) -> tuple[JsonObject, str]:
        identificatie = registry.tagged(f"afdeling-{name}")
        address = f"{identificatie}@example.invalid"
        data = {"naam": identificatie, "identificatie": identificatie} | ({"email": address} if email else {})
        make_object(objecten, registry, afdeling_type, data)
        return make_actor(openklant, registry, "organisatorische_eenheid", identificatie, "afd"), address

    def contactverzoek(actor: JsonObject, age: timedelta, *, closed: bool = False) -> str:
        geweest = (datetime.now(tz=UTC) - age).isoformat()
        onderwerp = registry.tagged(f"herinnering-{len(onderwerpen_made)}")
        onderwerpen_made.append(onderwerp)
        klantcontact = make_klantcontact(openklant, registry, onderwerp=onderwerp, plaatsgevondenOp=geweest)
        taak = make_internetaak(openklant, registry, klantcontact, [actor])
        clean_up_logboek(objecten, registry, logboek_type, str(taak["uuid"]))
        if closed:
            openklant.patch(str(taak["url"]), {"status": "verwerkt"})
        return onderwerp

    onderwerpen_made: list[str] = []
    overdue, overdue_address = afdeling("verlopen", email=True)
    onderwerpen = [contactverzoek(overdue, OVERDUE), contactverzoek(overdue, OVERDUE)]
    quiet, quiet_address = afdeling("rustig", email=True)
    contactverzoek(quiet, timedelta(hours=1))
    contactverzoek(quiet, OVERDUE, closed=True)
    no_mailbox, _ = afdeling("zonder-mailbox", email=False)
    contactverzoek(no_mailbox, OVERDUE)

    run_cronjob(podiumd_env.kube, cronjob, registry.tagged("herinnering"))
    body = received(
        mailpit, registry, timeout=MAIL_TIMEOUT, to=overdue_address, subject="2 contactverzoeken wachten op jou"
    )
    assert [o for o in onderwerpen if o in body] == [], "the reminder shows a contactverzoek's onderwerp"
    assert "/afdelings-contacten" in body
    found = mailpit.get("search", {"query": f'to:"{quiet_address}"'})
    assert entries(found.get("messages")) == [], f"a reminder to {quiet_address}"
