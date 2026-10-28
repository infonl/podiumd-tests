"""PKCE on the OIDC logins. Ported from podiumd-minikube and podiumd-infra test_pkce.py.

PABC always sends a PKCE code challenge (UsePkce is hard-coded in its source); every test in
component/pabc logs in through it, so Keycloak accepts the verifier. The Django apps' clients must
not require PKCE (mozilla-django-oidc does not send it), nor ita's and kiss's: they send it, but the
podiumd chart does not require it.
ZAC sends a challenge when zac.auth.enablePkce is on (default from podiumd 4.10.0, helm-charts #629); the
same key sets pkce.code.challenge.method S256 on the zac client, so the two must agree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs
from urllib.parse import urlsplit

import pytest

from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.json_data import section
from podiumd_tests.responses import url_host
from podiumd_tests.workloads import chart_older_than

if TYPE_CHECKING:
    import requests

    from podiumd_tests.auth.keycloak_admin import KeycloakAdmin
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.requires("keycloak")]

# Keycloak client ids, not component names: Open Archiefbeheer's client is "abc". The podiumd realm renders it
# also where Open Archiefbeheer is off. podiumd 4.10 has no "objecttypen" client (Open Object serves the
# Objecttypen API with client "objecten"); it skips there and is checked on older charts.
NO_PKCE_REQUIRED = (
    "openzaak",
    "openklant",
    "objecten",
    "objecttypen",
    "opennotificaties",
    "openformulieren",
    "abc",
    "ita",
    "kiss",
)


@pytest.fixture(scope="module", name="keycloak_admin")
def fixture_keycloak_admin(podiumd_env: Environment) -> KeycloakAdmin:
    """Admin API of the environment's realm."""
    return for_environment(podiumd_env)


@pytest.mark.requires("pabc")
@pytest.mark.source(
    "MK test_pkce.py", "Verifies PKCE for every Keycloak client that podiumd-minikube wires an OIDC login for."
)
@pytest.mark.source(
    "PI test_pkce.py", "Guards that no Keycloak client starts requiring PKCE without a verified app-side capability."
)
def test_pabc_challenge_sends_a_pkce_code_challenge(http: requests.Session, urls: dict[str, str]) -> None:
    """PABC's login challenge points at Keycloak with client pabc and an S256 code challenge."""
    response = http.get(urls["pabc"] + "/api/challenge", params={"returnUrl": "/"}, allow_redirects=False)
    location = response.headers["Location"]  # 401 for a non-browser request, 302 for a browser
    assert url_host(location) == url_host(urls["keycloak"])
    query = parse_qs(urlsplit(location).query)
    assert query["client_id"] == ["pabc"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"][0]


@pytest.mark.parametrize("client_id", NO_PKCE_REQUIRED)
@pytest.mark.source(
    "MK test_pkce.py", "Verifies PKCE for every Keycloak client that podiumd-minikube wires an OIDC login for."
)
@pytest.mark.source(
    "PI test_pkce.py", "Guards that no Keycloak client starts requiring PKCE without a verified app-side capability."
)
def test_client_does_not_require_pkce(keycloak_admin: KeycloakAdmin, client_id: str) -> None:
    """The client leaves pkce.code.challenge.method empty: its app sends no challenge, or the chart does not require one."""
    client = keycloak_admin.client(client_id)
    if client is None:
        pytest.skip(f"no Keycloak client {client_id} in this realm")
    assert section(client, "attributes").get("pkce.code.challenge.method", "") == ""


ZAC_PKCE_OFF = (
    "[podiumd-chart-21] podiumd before 4.10.0 leaves ZAC's PKCE off: no code challenge (zac.auth.enablePkce,"
    " helm-charts #629)"
)


def zac_login_query(http: requests.Session, urls: dict[str, str]) -> dict[str, list[str]]:
    """The query of the Keycloak URL ZAC's root redirects an anonymous browser to."""
    response = http.get(urls["zac"] + "/", allow_redirects=False)
    location = response.headers.get("Location", "")
    assert url_host(location) == url_host(urls["keycloak"]), f"ZAC's root does not redirect to Keycloak: {location!r}"
    return parse_qs(urlsplit(location).query)


@pytest.mark.requires("zac")
@pytest.mark.source(
    "podiumd-tests", "helm-charts #629 turns ZAC's PKCE on by default; ZAC and its Keycloak client must agree on it."
)
def test_zac_login_sends_an_s256_code_challenge(
    http: requests.Session, urls: dict[str, str], podiumd_env: Environment
) -> None:
    """ZAC's login redirect to Keycloak carries an S256 code challenge (PKCE)."""
    query = zac_login_query(http, urls)
    assert query.get("client_id") == ["zac"]
    if not query.get("code_challenge") and chart_older_than(podiumd_env, (4, 10, 0)):
        pytest.xfail(ZAC_PKCE_OFF)
    assert query.get("code_challenge_method") == ["S256"]


@pytest.mark.requires("zac")
@pytest.mark.source(
    "podiumd-tests", "helm-charts #629 turns ZAC's PKCE on by default; ZAC and its Keycloak client must agree on it."
)
def test_zac_client_and_zac_agree_on_pkce(
    http: requests.Session, urls: dict[str, str], keycloak_admin: KeycloakAdmin
) -> None:
    """The zac client requires S256 exactly when ZAC sends a challenge; one side alone breaks or weakens the login."""
    client = keycloak_admin.client("zac")
    if client is None:
        pytest.skip("no Keycloak client zac in this realm")
    sends = bool(zac_login_query(http, urls).get("code_challenge"))
    method = section(client, "attributes").get("pkce.code.challenge.method") or ""
    assert method == ("S256" if sends else ""), f"ZAC sends a challenge: {sends}; client zac requires: {method!r}"
