"""ApiClients for the platform APIs with the suite's own bootstrap credentials.

The pytest fixtures and the sweep command build their clients here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from podiumd_tests.auth.zgw_jwt import zgw_headers
from podiumd_tests.auth.zgw_jwt import zgw_jwt
from podiumd_tests.bootstrap.steps import NRC_CLIENT_ID
from podiumd_tests.bootstrap.steps import NRC_STORE_KEY
from podiumd_tests.bootstrap.steps import OBJECTEN_STORE_KEY
from podiumd_tests.bootstrap.steps import OPENKLANT_STORE_KEY
from podiumd_tests.clients.api import ApiClient

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.environment import Environment


def openzaak_client(
    env: Environment, client_id: str, store_key: str, run_tag: str, audit: Callable[[], str] = lambda: ""
) -> ApiClient:
    """Open Zaak's ZGW APIs as one of the suite's clients, with a fresh token per request.

    Each change in Open Zaak's audittrail names the run, and audit() (e.g. the running test).
    """
    secret = env.credentials.get(store_key)

    def headers() -> dict[str, str]:
        token = zgw_jwt(client_id, secret, user=f"podiumd-tests {run_tag}")
        return {**zgw_headers(token), "X-Audit-Toelichting": f"{run_tag} {audit()}".strip()[:255]}

    return ApiClient(env.session(cookies=False), env.profile.urls["openzaak"], headers)


def opennotificaties_client(env: Environment) -> ApiClient:
    """Open Notificaties as the suite's own client ptest-bootstrap-nrc."""
    secret = env.credentials.get(NRC_STORE_KEY)
    url = env.profile.urls["opennotificaties"] + "/api/v1"
    return ApiClient(env.session(cookies=False), url, lambda: zgw_headers(zgw_jwt(NRC_CLIENT_ID, secret)))


def openklant_client(env: Environment) -> ApiClient:
    """Open Klant's klantinteracties API with the suite's own token."""
    token = env.credentials.get(OPENKLANT_STORE_KEY)
    url = env.profile.urls["openklant"] + "/klantinteracties/api/v1"
    return ApiClient(env.session(cookies=False), url, {"Authorization": f"Token {token}"})


def objecten_client(env: Environment) -> ApiClient:
    """Objecten API with the suite's own token."""
    token = env.credentials.get(OBJECTEN_STORE_KEY)
    headers = {"Authorization": f"Token {token}", "Content-Crs": "EPSG:4326", "Accept-Crs": "EPSG:4326"}
    return ApiClient(env.session(cookies=False), env.profile.urls["objecten"] + "/api/v2", headers)


def mailpit_client(env: Environment) -> ApiClient:
    """The environment's Mailpit API."""
    return ApiClient(env.session(cookies=False), env.profile.urls["mailpit"] + "/api/v1", {})
