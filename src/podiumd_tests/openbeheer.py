"""Open Beheer's API (catalogi management on top of Open Zaak), in a Keycloak login session."""

from __future__ import annotations

from typing import TYPE_CHECKING

from podiumd_tests.auth.keycloak import form_login

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment


def openbeheer_session(env: Environment, username: str, password: str) -> requests.Session:
    """A session on Open Beheer's API, logged in through its OIDC login (cookie authentication)."""
    http = env.session()
    form_login(http, env.profile.urls["openbeheer"] + "/auth/oidc/authenticate/?next=/", username, password)
    return http
