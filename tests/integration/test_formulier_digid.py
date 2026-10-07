"""Chain: a form submitted after a DigiD login registers a zaak with the inwoner as initiator.

Ported from TA regression 183. DigiD is Keycloak's mock (wiring W1); without a login Open
Formulieren registers no initiator, and with eHerkenning the 8-digit KvK is too short for Open Zaak.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_FORM
from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.browser import browser_session
from podiumd_tests.browser import keycloak_login
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.openformulieren import delete_submission
from podiumd_tests.openformulieren import submit
from podiumd_tests.responses import url_host
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.sync_api import Page

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.ui,
    pytest.mark.core,
    pytest.mark.requires("openformulieren", "openzaak", "keycloak"),
]

INWONER = IDENTITIES[0]
REGISTRATION_TIMEOUT = 90


def test_digid_submission_has_the_inwoner_as_initiator(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """The zaak of a DigiD submission has a natuurlijk-persoon initiator with the inwoner's BSN and the PDF."""
    need_bootstrap("openformulieren-oidc-mock", INWONER.name)
    base = podiumd_env.profile.urls["openformulieren"]
    form_url = f"{base}/{TEST_FORM}/"
    form = browser_session(page, podiumd_env).get(f"{base}/api/v2/forms/{TEST_FORM}").json()
    digid = next(o for o in entries(form["loginOptions"]) if o.get("identifier") == "digid_oidc")
    page.goto(f"{digid['url']}?next={form_url}")
    keycloak_login(page, INWONER.username, podiumd_env.credentials.get(INWONER.store_key))
    page.wait_for_url(lambda url: url_host(url) == url_host(base) and "/callback" not in url)

    status = submit(
        browser_session(page, podiumd_env),
        base,
        TEST_FORM,
        {"klacht_omschrijving": registry.tagged("digid-klacht")},
        timeout=REGISTRATION_TIMEOUT,
    )
    submission = str(status["submission"])
    registry.add(f"submission {submission}", lambda: delete_submission(podiumd_env, submission))
    zaken = openzaak.list(f"{ZAKEN}/zaken", {"identificatie": str(status["publicReference"])})
    zaak = str(zaken[0]["url"])
    registry.add(f"zaak {zaak}", lambda: delete_zaak(openzaak, zaak))
    rollen = openzaak.list(f"{ZAKEN}/rollen", {"zaak": zaak})
    initiators = [r for r in rollen if r.get("betrokkeneType") == "natuurlijk_persoon"]
    assert [section(r, "betrokkeneIdentificatie").get("inpBsn") for r in initiators] == [INWONER.attributes["bsn"][0]]
    assert openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": zaak})
