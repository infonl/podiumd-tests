"""ZAC's signalering TAAK_AFGEROND: the behandelaar of a zaak gets a mail when someone else completes a taak on it.

From ZAC 5.12.0 (#7813, #7822): mail only, on by default, with the system mailtemplate "Signalering taak afgerond".
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.keycloak_admin import user_email
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.mailpit import delete_mails
from podiumd_tests.mailpit import quoted
from podiumd_tests.mailpit import received_mails
from podiumd_tests.mailpit import search
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.seed.zac_zaaktype import make_group_member
from podiumd_tests.seed.zac_zaaktype import make_role_group
from podiumd_tests.wait import is_never
from podiumd_tests.workloads import skip_older_than
from podiumd_tests.zac import toekennen
from podiumd_tests.zac import zac_session
from podiumd_tests.zac_beheer import MAILTEMPLATES
from podiumd_tests.zac_signaleringen import signalering_settings
from podiumd_tests.zac_signaleringen import turn_signaleringen
from podiumd_tests.zac_taken import ADVIES_INTERN
from podiumd_tests.zac_taken import complete_task
from podiumd_tests.zac_taken import started_taak

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "openzaak", "keycloak", "pabc", "cluster", "mailpit"),
    # Fixture zac_taken_zaaktype: one throwaway zaaktype per run, shared with test_zac_taken.py.
    pytest.mark.xdist_group("zac-taken-zaaktype"),
]

TAAK_AFGEROND = "TAAK_AFGEROND"
# The release that signals a taak someone else completed on the user's zaak (#7822).
SIGNALS_TAAK_AFGEROND = (5, 12, 0)
MAIL_TIMEOUT = 60
VRAAG = {"vraag": "podiumd-tests vraag"}
ADVIES = {"advies": "Positief"}


def _afgerond_mails(username: str, zaak: JsonObject) -> str:
    """The Mailpit query for TAAK_AFGEROND mails to the user about the zaak (the mailtemplate's body)."""
    tekst = f"heeft een taak afgerond voor zaak {zaak['identificatie']}"
    return f"to:{quoted(user_email(username))} {quoted(tekst)}"


def _behandelaar_of(
    env: Environment, zac: requests.Session, zac_url: str, zaak: JsonObject, registry: ResourceRegistry
) -> tuple[str, requests.Session]:
    """Make a new member of a new behandelaar group the zaak's behandelaar; their username and session."""
    group = make_role_group(env, registry, "behandelaar")
    username, password = make_group_member(env, registry, group)
    expect_status(toekennen(zac, zac_url, zaak, group, username), HTTPStatus.OK)
    return username, zac_session(env, username, password)


def _admin_completes_a_taak(zac: requests.Session, zac_url: str, zaak: JsonObject, groep: str) -> None:
    taak = started_taak(zac, zac_url, zaak, ADVIES_INTERN, (groep, ADMIN.username), taakdata=VRAAG)
    complete_task(zac, zac_url, taak, ADVIES)


@pytest.mark.source(
    "PZW Sprint 83 PZ-11287",
    "When a taak of the behandelaar's zaak is completed by someone else, the behandelaar gets a signalering mail.",
)
@pytest.mark.scenario("""
    Given a zaak in behandeling of a behandelaar who wants a mail for taken others complete on their zaken
    When the test admin completes an Advies intern on the zaak
    Then the behandelaar gets a mail that the admin completed a taak for that zaak
""")
def test_taak_completed_by_someone_else_mails_the_behandelaar(  # the users, zaak and mailbox
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    behandeling: JsonObject,
    zac_group: str,
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """TAAK_AFGEROND with mail on mails the zaak's behandelaar after another user completes a taak."""
    skip_older_than(podiumd_env, "zac", SIGNALS_TAAK_AFGEROND, "no signalering TAAK_AFGEROND")
    zac_url = urls["zac"]
    naam, behandelaar = _behandelaar_of(podiumd_env, zac, zac_url, behandeling, registry)
    turn_signaleringen(behandelaar, zac_url, registry, mail=True, TAAK_AFGEROND=False)
    _admin_completes_a_taak(zac, zac_url, behandeling, zac_group)
    query = _afgerond_mails(naam, behandeling)
    assert received_mails(mailpit, registry, query, timeout=MAIL_TIMEOUT)


@pytest.mark.source(
    "PZW Sprint 83 PZ-11287",
    "With 'Een taak van mijn zaak is door iemand anders afgerond' off, completing a taak sends no signalering mail.",
)
@pytest.mark.scenario("""
    Given a zaak in behandeling of a behandelaar who turned off the mail for taken others complete on their zaken
    When the test admin completes an Advies intern on the zaak
    Then the behandelaar gets no mail about it
""")
def test_taak_afgerond_mail_off_sends_none(  # the users, zaak and mailbox
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    behandeling: JsonObject,
    zac_group: str,
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """TAAK_AFGEROND with mail off sends no mail."""
    skip_older_than(podiumd_env, "zac", SIGNALS_TAAK_AFGEROND, "no signalering TAAK_AFGEROND")
    zac_url = urls["zac"]
    naam, behandelaar = _behandelaar_of(podiumd_env, zac, zac_url, behandeling, registry)
    turn_signaleringen(behandelaar, zac_url, registry, mail=False, TAAK_AFGEROND=False)
    _admin_completes_a_taak(zac, zac_url, behandeling, zac_group)
    query = _afgerond_mails(naam, behandeling)
    registry.add(f"mails {query}", lambda: delete_mails(mailpit, query))
    assert is_never(lambda: search(mailpit, query), timeout=MAIL_TIMEOUT, description=f"a TAAK_AFGEROND mail to {naam}")


@pytest.mark.source(
    "PZW Sprint 83 PZ-11287",
    "The signalering is on by default, and ZAC has the system mailtemplate 'Signalering taak afgerond'.",
)
@pytest.mark.scenario("""
    Given a new ZAC user who never changed a signalering setting
    Then the user's setting for taken others complete on their zaken has the mail on
    And ZAC's beheer has the default mailtemplate Signalering taak afgerond
""")
def test_taak_afgerond_is_on_by_default_with_its_mailtemplate(
    podiumd_env: Environment, zac: requests.Session, urls: dict[str, str], registry: ResourceRegistry
) -> None:
    """A new user's TAAK_AFGEROND setting mails; mailtemplate SIGNALERING_TAAK_AFGEROND is a default one."""
    skip_older_than(podiumd_env, "zac", SIGNALS_TAAK_AFGEROND, "no signalering TAAK_AFGEROND")
    zac_url = urls["zac"]
    group = make_role_group(podiumd_env, registry, "behandelaar")
    username, password = make_group_member(podiumd_env, registry, group)
    settings = signalering_settings(zac_session(podiumd_env, username, password), zac_url)
    assert [(s.get("type"), s.get("mail")) for s in settings if s.get("type") == TAAK_AFGEROND] == [
        (TAAK_AFGEROND, True)
    ]
    templates = get_entries(zac, zac_url + MAILTEMPLATES)
    found = [
        (t.get("mailTemplateNaam"), t.get("defaultMailtemplate"))
        for t in templates
        if t.get("mail") == "SIGNALERING_TAAK_AFGEROND"
    ]
    assert found == [("Signalering taak afgerond", True)]
