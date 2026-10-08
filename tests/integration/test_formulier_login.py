"""Chain: a form submitted after a DigiD or eHerkenning login registers a zaak with that initiator.

Ported from TA regression 158, 159 and 183. DigiD and eHerkenning are Keycloak's mock (wiring W1);
without a login Open Formulieren registers no initiator.
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
from podiumd_tests.openformulieren import registered_zaak
from podiumd_tests.openformulieren import submit
from podiumd_tests.responses import url_host
from podiumd_tests.seed.openzaak import ZAKEN

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.sync_api import Page

    from podiumd_tests.bootstrap.steps import KeycloakUser
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.ui,
    pytest.mark.core,
    pytest.mark.requires("openformulieren", "openzaak", "keycloak"),
]

INWONER, _, BEDRIJF = IDENTITIES
REGISTRATION_TIMEOUT = 90


def submit_after_login(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # one flow
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    method: str,
    user: KeycloakUser,
) -> list[JsonObject]:
    """Log in on the test form with method (digid_oidc, eherkenning_oidc), submit it; the rollen of its zaak."""
    base = podiumd_env.profile.urls["openformulieren"]
    form_url = f"{base}/{TEST_FORM}/"
    form = browser_session(page, podiumd_env).get(f"{base}/api/v2/forms/{TEST_FORM}").json()
    login = next(o for o in entries(form["loginOptions"]) if o.get("identifier") == method)
    page.goto(f"{login['url']}?next={form_url}")
    keycloak_login(page, user.username, podiumd_env.credentials.get(user.store_key))
    page.wait_for_url(lambda url: url_host(url) == url_host(base) and "/callback" not in url)
    # The form's SDK in the page shares the session and overwrites it with its own requests,
    # which loses the submission the API calls below put in it (403).
    page.goto("about:blank")
    status = submit(
        browser_session(page, podiumd_env),
        base,
        TEST_FORM,
        {"klacht_omschrijving": registry.tagged(f"{method}-klacht")},
        timeout=REGISTRATION_TIMEOUT,
    )
    zaak = str(registered_zaak(podiumd_env, openzaak, registry, status)["url"])
    assert openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": zaak})
    return openzaak.list(f"{ZAKEN}/rollen", {"zaak": zaak})


@pytest.mark.tc("ARCH-019")
def test_digid_submission_has_the_inwoner_as_initiator(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """The zaak of a DigiD submission has a natuurlijk-persoon initiator with the inwoner's BSN and the PDF (TA reg-183)."""
    need_bootstrap("openformulieren-oidc-mock", INWONER.name)
    rollen = submit_after_login(page, podiumd_env, openzaak, registry, "digid_oidc", INWONER)
    initiators = [r for r in rollen if r.get("betrokkeneType") == "natuurlijk_persoon"]
    assert [section(r, "betrokkeneIdentificatie").get("inpBsn") for r in initiators] == [INWONER.attributes["bsn"][0]]


def test_eherkenning_submission_has_the_vestiging_as_initiator(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """The zaak of an eHerkenning submission has the company's vestiging as initiator (TA reg-158, reg-159)."""
    need_bootstrap("openformulieren-oidc-mock", BEDRIJF.name)
    rollen = submit_after_login(page, podiumd_env, openzaak, registry, "eherkenning_oidc", BEDRIJF)
    initiators = [section(r, "betrokkeneIdentificatie") for r in rollen if r.get("omschrijvingGeneriek") == "initiator"]
    assert [(i.get("kvkNummer"), i.get("vestigingsNummer")) for i in initiators] == [
        (BEDRIJF.attributes["kvk"][0], BEDRIJF.attributes["vestigingsnummer"][0])
    ]
