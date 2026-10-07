"""Open Inwoner in a browser: DigiD and eHerkenning login through Keycloak's mock end in a session.

Ported from ExternalsPodiumD smoke 05b and 99 (TA portaal login specs); needs wiring W1.
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.openinwoner import portal_login

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.sync_api import Page

    from podiumd_tests.bootstrap.steps import KeycloakUser
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.core, pytest.mark.requires("openinwoner", "keycloak")]

INWONER, _, BEDRIJF = IDENTITIES
FAILED = re.compile(r"/(accounts/login|login/failure)/")


@pytest.mark.parametrize(
    ("method", "user"), [("digid", INWONER), ("eherkenning", BEDRIJF)], ids=["digid", "eherkenning"]
)
def test_login_through_the_keycloak_mock_starts_a_session(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    need_bootstrap: Callable[..., None],
    method: str,
    user: KeycloakUser,
) -> None:
    """The test identity logs in and lands on the portal, not on a login or failure page."""
    need_bootstrap(user.name, "openinwoner-oidc-mock")
    portal_login(page, podiumd_env, method, user)
    expect(page).not_to_have_url(FAILED)
    cookies = [c.get("name") for c in page.context.cookies()]
    assert "open_inwoner_sessionid" in cookies, "no Open Inwoner session cookie"
