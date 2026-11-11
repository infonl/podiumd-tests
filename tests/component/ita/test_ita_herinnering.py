"""ITA's daily reminder mail for overdue contactverzoeken, per afdeling.

ITA's poller (POLLER_MODE verlopen-contactverzoek-herinnering-notificatie) mails every actor with contactverzoeken
whose klantcontact took place more than ITA's afhandeltermijn of weekday hours ago and that are still
te_verwerken. podiumd 4.10 leaves its CronJob off (ita.verlopenContactverzoekHerinneringNotificatie.enabled,
DRT-726), so the test runs ITA's poller once in that mode from the CronJob of new contactverzoeken where the reminder
CronJob is missing. The run mails every overdue actor of the environment: destructive, and only where Mailpit
catches the mail.
"""

from __future__ import annotations

import math
import re

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.ita import mailbox
from podiumd_tests.ita import make_eenheid
from podiumd_tests.ita import make_medewerker
from podiumd_tests.kcc import ita_afhandeltermijn_hours
from podiumd_tests.kube import metadata_name
from podiumd_tests.mailpit import quoted
from podiumd_tests.mailpit import received
from podiumd_tests.mailpit import search
from podiumd_tests.seed.objecten import clean_up_logboek
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openklant import close_internetaak
from podiumd_tests.seed.openklant import make_actor
from podiumd_tests.seed.openklant import make_betrokkene
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
# ITA's poller CronJob of new contactverzoeken, on in every environment; same image, POLLER_MODE picks the job.
POLLER = "-nieuw-cv-notify"
MAIL_TIMEOUT = 60
# The voornaam make_betrokkene gives the klant.
KLANTNAAM = "PodiumD"
# The werkvoorraad a reminder links to: an afdeling's; a medewerker's is "/".
AFDELING = "/afdelings-contacten"


def reminder_job(env: Environment) -> tuple[str, dict[str, str]]:
    """Return the CronJob that runs ITA's reminder, and the env that puts its poller in reminder mode if needed.

    The reminder's own CronJob where the environment turns it on, else ITA's CronJob of new contactverzoeken.
    """
    names = [metadata_name(c) for c in env.items("cronjobs")]
    reminder = [n for n in names if n.endswith(REMINDER)]
    if reminder:
        return reminder[0], {}
    poller = [n for n in names if n.endswith(POLLER)]
    if not poller:
        pytest.skip(f"ITA has no poller CronJob (*{REMINDER} or *{POLLER}) here")
    return poller[0], {"POLLER_MODE": "verlopen-contactverzoek-herinnering-notificatie"}


def overdue_age(env: Environment) -> timedelta:
    """An age past ITA's afhandeltermijn whatever day the test runs: weekday hours, plus a weekend and a margin."""
    return timedelta(days=math.ceil(ita_afhandeltermijn_hours(env) / 24 * 7 / 5) + 4)


def _medewerker_with_afdeling(
    env: Environment,
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    afdeling: JsonObject,
    age: timedelta,
) -> str:
    """Create an overdue contactverzoek of a klant assigned to a new medewerker and the afdeling; the medewerker."""
    medewerker = make_medewerker(env, objecten, openklant, registry, with_email=True)
    actor = make_actor(openklant, registry, "medewerker", medewerker, "mdw")
    klantcontact = make_klantcontact(openklant, registry, plaatsgevondenOp=(datetime.now(tz=UTC) - age).isoformat())
    make_betrokkene(openklant, registry, klantcontact, None)
    taak = make_internetaak(openklant, registry, klantcontact, [actor, afdeling])
    clean_up_logboek(objecten, registry, objecttype_url(env, "Activiteitenlog"), str(taak["uuid"]))
    return medewerker


def _assert_reminder(  # the mail and what it must and must not show
    mailpit: ApiClient, registry: ResourceRegistry, address: str, subject: str, link: str, hidden: list[str]
) -> None:
    """The address gets the reminder with the subject, linking to the path, without any of hidden in its body."""
    body = received(mailpit, registry, timeout=MAIL_TIMEOUT, to=address, subject=subject)
    assert re.search(rf'href="https?://[^"/]+{link}"', body), f"the reminder to {address} links not to {link}"
    assert [text for text in hidden if text in body] == [], f"the reminder to {address} shows personal data"


@pytest.mark.source(
    f"{E2E}/DagelijkseHerinneringScenarios.cs",
    "An afdeling gets one aggregated reminder for its overdue contactverzoeken, without personal data in the body.",
)
@pytest.mark.source(
    f"{E2E}/DagelijkseHerinneringScenarios.cs",
    "No reminder for a contactverzoek that is closed or not yet overdue; an afdeling without e-mail blocks no one.",
)
@pytest.mark.source(
    f"{E2E}/DagelijkseHerinneringScenarios.cs",
    "A medewerker gets a reminder linking to their werkvoorraad; assigned to a medewerker and an afdeling, both get one.",
)
@pytest.mark.scenario("""
    Given an afdeling with two overdue contactverzoeken
    And an afdeling with only a recent and a closed contactverzoek
    And an overdue contactverzoek of a klant, assigned to a medewerker and a third afdeling
    When ITA's daily reminder runs
    Then the first afdeling gets one mail "2 contactverzoeken wachten op jou" with a link to its contacten
    And the mail shows no onderwerp of a contactverzoek
    And the second afdeling gets no mail
    And the medewerker and the third afdeling each get "1 contactverzoek wacht op jou", the medewerker's linking to their werkvoorraad
    And neither mail shows the klant's name
""")
def test_afdeling_gets_one_reminder_for_its_overdue_contactverzoeken(
    podiumd_env: Environment,
    openklant: ApiClient,
    objecten: ApiClient,
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """Two overdue contactverzoeken of an afdeling give it one mail; recent, closed and mailbox-less ones give none."""
    cronjob, mode = reminder_job(podiumd_env)
    overdue_for = overdue_age(podiumd_env)
    logboek_type = objecttype_url(podiumd_env, "Activiteitenlog")

    def afdeling(*, email: bool) -> tuple[JsonObject, str]:
        identificatie = make_eenheid(podiumd_env, objecten, openklant, registry, "Afdeling", with_mailbox=email)
        return make_actor(openklant, registry, "organisatorische_eenheid", identificatie, "afd"), mailbox(identificatie)

    def contactverzoek(actor: JsonObject, age: timedelta, *, closed: bool = False) -> str:
        geweest = (datetime.now(tz=UTC) - age).isoformat()
        onderwerp = registry.tagged(f"herinnering-{len(onderwerpen_made)}")
        onderwerpen_made.append(onderwerp)
        klantcontact = make_klantcontact(openklant, registry, onderwerp=onderwerp, plaatsgevondenOp=geweest)
        taak = make_internetaak(openklant, registry, klantcontact, [actor])
        clean_up_logboek(objecten, registry, logboek_type, str(taak["uuid"]))
        if closed:
            close_internetaak(openklant, taak)
        return onderwerp

    onderwerpen_made: list[str] = []
    overdue, overdue_address = afdeling(email=True)
    onderwerpen = [contactverzoek(overdue, overdue_for), contactverzoek(overdue, overdue_for)]
    quiet, quiet_address = afdeling(email=True)
    no_mailbox, _ = afdeling(email=False)
    # Recent, closed, or of an afdeling without mailbox: no reminder.
    for actor, age, closed in (
        (quiet, timedelta(hours=1), False),
        (quiet, overdue_for, True),
        (no_mailbox, overdue_for, False),
    ):
        contactverzoek(actor, age, closed=closed)

    gedeeld, gedeeld_address = afdeling(email=True)
    medewerker = _medewerker_with_afdeling(podiumd_env, openklant, objecten, registry, gedeeld, overdue_for)

    run_cronjob(podiumd_env.kube, cronjob, registry.tagged("herinnering"), env=mode)
    _assert_reminder(mailpit, registry, overdue_address, "2 contactverzoeken wachten op jou", AFDELING, onderwerpen)
    assert search(mailpit, f"to:{quoted(quiet_address)}") == [], f"a reminder to {quiet_address}"
    for address, link in ((mailbox(medewerker), "/"), (gedeeld_address, AFDELING)):
        _assert_reminder(mailpit, registry, address, "1 contactverzoek wacht op jou", link, [KLANTNAAM])
