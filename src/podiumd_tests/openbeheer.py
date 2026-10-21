"""Open Beheer's API (catalogi management on top of Open Zaak), in a Keycloak login session."""

from __future__ import annotations

from typing import TYPE_CHECKING

from podiumd_tests.auth.keycloak import form_login
from podiumd_tests.oidc import LOGIN_PATHS

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment


def openbeheer_session(env: Environment, username: str, password: str) -> requests.Session:
    """A session on Open Beheer's API, logged in through its OIDC login (cookie authentication).

    Its writes need Django's CSRF token and a Referer of Open Beheer itself, which the session sends.
    """
    http = env.session()
    base_url = env.profile.urls["openbeheer"]
    form_login(http, base_url + LOGIN_PATHS["openbeheer"], username, password)
    http.headers.update({"X-CSRFToken": http.cookies.get("csrftoken") or "", "Referer": base_url + "/"})
    return http
