"""Is login wired to Keycloak? Without logging in: follow the redirects to the login page.

Ported from TA/EX smoke 82 (portaal login config), 05a (DigiD link),
99 test 1 (eHerkenning link), 81 (Keycloak realm) and the first leg of MK/PI
test_login_flow.py. The realm is read from the redirect, not configured:
minikube uses realm zaakafhandelcomponent for ZAC, the QA estates podiumd.
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.oidc import keycloak_login_realm

if TYPE_CHECKING:
    import requests

pytestmark = pytest.mark.smoke


@pytest.mark.requires("keycloak")
def test_keycloak_discovery(http: requests.Session, urls: dict[str, str]) -> None:
    """The master realm publishes its OIDC configuration."""
    response = http.get(urls["keycloak"] + "/realms/master/.well-known/openid-configuration")
    assert response.status_code == 200
    assert str(response.json()["issuer"]).endswith("/realms/master")


@pytest.mark.requires("zac", "keycloak")
def test_zac_redirects_to_keycloak(http: requests.Session, urls: dict[str, str]) -> None:
    """An anonymous visit to ZAC ends on the Keycloak login form, and that realm is published."""
    realm = keycloak_login_realm(http.get(urls["zac"] + "/"), urls["keycloak"])
    discovery = http.get(f"{urls['keycloak']}/realms/{realm}/.well-known/openid-configuration")
    assert discovery.status_code == 200


@pytest.mark.requires("openinwoner")
def test_portaal_login_page_offers_digid_and_eherkenning(http: requests.Session, urls: dict[str, str]) -> None:
    """The Open Inwoner login page has the theme and both login options (82, 05a, 99)."""
    response = http.get(urls["openinwoner"] + "/accounts/login/")
    assert response.status_code == 200, f"{response.url}: HTTP {response.status_code}"
    html = response.text
    assert "openinwoner-theme" in html
    assert "/digid-oidc/authenticate/" in html, "no DigiD login link"
    assert "/eherkenning-oidc/authenticate/" in html, "no eHerkenning login link"
    assert re.search(r"Log in met DigiD", html, re.IGNORECASE), "no 'Log in met DigiD' text"


@pytest.mark.requires("openinwoner", "keycloak")
@pytest.mark.parametrize("method", ["digid", "eherkenning"])
def test_portaal_login_redirects_to_keycloak(http: requests.Session, urls: dict[str, str], method: str) -> None:
    """Starting a DigiD or eHerkenning login ends on the Keycloak login form (82 test 4, 05b and 99 first leg)."""
    keycloak_login_realm(http.get(f"{urls['openinwoner']}/{method}-oidc/authenticate/?next=/"), urls["keycloak"])
