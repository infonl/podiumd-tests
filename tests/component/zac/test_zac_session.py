"""ZAC's session outlives its access token: ZAC refreshes the tokens itself, also with PKCE on.

ZAC keeps the user's tokens in its server-side session and uses the refresh token when the access token has
expired. Keycloak rotates refresh tokens where revokeRefreshToken is on, so a second refresh only works when ZAC
stored the new refresh token of the first. The test waits out the realm's access token lifespan twice; it skips
where that lifespan makes the wait too long.
"""

from __future__ import annotations

import time

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.responses import describe

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "keycloak")]

LOGGED_IN_USER = "/rest/identity/loggedInUser"
# Longer than this per wait (seconds) and the test skips; podiumd-infra's realms use 60.
MAX_WAIT = 300
# Past the token's expiry, so the next request needs a refresh.
MARGIN = 15


def logged_in_user(zac: requests.Session, zac_url: str) -> str:
    """The id of the user ZAC's session belongs to; fails on a redirect to the login."""
    response = zac.get(zac_url + LOGGED_IN_USER, allow_redirects=False)
    assert response.status_code == HTTPStatus.OK, describe(response)
    return str(response.json()["id"])


def test_session_survives_two_token_refreshes(
    zac: requests.Session, urls: dict[str, str], podiumd_env: Environment
) -> None:
    """Twice after the access token expired, ZAC still answers as the logged-in user."""
    lifespan = int(str(for_environment(podiumd_env).representation().get("accessTokenLifespan") or 0))
    if not 0 < lifespan <= MAX_WAIT:
        pytest.skip(f"realm accessTokenLifespan {lifespan}s: waiting it out twice takes too long")
    assert logged_in_user(zac, urls["zac"]) == ADMIN.username
    for _ in range(2):
        time.sleep(lifespan + MARGIN)
        assert logged_in_user(zac, urls["zac"]) == ADMIN.username
