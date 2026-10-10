"""Security baseline of every public host: headers, session cookies, CORS and the TLS certificate.

Neither estate's edge adds security headers, so each app must send its own (PLAN §13).
"""

from __future__ import annotations

import time

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.components import COMPONENTS
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.responses import describe
from podiumd_tests.security import MIN_CERT_DAYS
from podiumd_tests.security import days_valid
from podiumd_tests.security import foreign_origin_allowed
from podiumd_tests.security import insecure_session_cookies
from podiumd_tests.security import missing_security_headers

if TYPE_CHECKING:
    import requests

    from _pytest.mark.structures import ParameterSet

    from podiumd_tests.environment import Environment

pytestmark = pytest.mark.smoke

# Mailpit is minikube's mail sink, api-proxy has no public host on the estates.
NOT_PUBLIC = ("mailpit", "api-proxy")
PUBLIC = sorted(set(COMPONENTS) - set(NOT_PUBLIC))
FOREIGN_ORIGIN = "https://ptest-foreign.example.invalid"
# Apps that send none or part of the headers themselves; xfail without strict, as an edge may add them.
HEADER_GAPS = {
    "zac": "ZAC itself sends no HSTS or nosniff, its chart's nginx adds them; minikube runs ZAC without it",
    "pabc": "PABC sends no HSTS, nosniff or frame protection",
    "ita": "ITA sends no HSTS and no nosniff",
    "openarchiefbeheer": "Open Archiefbeheer sends no HSTS and no nosniff",
    "openformulieren": "Open Formulieren sends no HSTS",
    "grafana": "Grafana sends no HSTS (its strict_transport_security setting is off)",
}


def headers_param(component: str) -> ParameterSet:
    """The component as a parameter, xfail where HEADER_GAPS knows it lacks headers."""
    gap = HEADER_GAPS.get(component)
    marks = [pytest.mark.xfail(strict=False, reason=f"{gap}; not yet reported upstream")] if gap else []
    return requiring(component, component, marks=marks)


@pytest.mark.parametrize("component", [headers_param(c) for c in PUBLIC])
def test_security_headers(http: requests.Session, urls: dict[str, str], component: str) -> None:
    """The root sends HSTS and nosniff, and frame protection when it is an HTML page."""
    response = http.get(urls[component] + "/", allow_redirects=False)
    assert not missing_security_headers(response), f"{describe(response)} lacks {missing_security_headers(response)}"


@pytest.mark.parametrize("component", [requiring(c, c) for c in PUBLIC])
def test_session_cookies_are_secure(http: requests.Session, urls: dict[str, str], component: str) -> None:
    """Session, auth and token cookies the root sets are Secure and HttpOnly."""
    response = http.get(urls[component] + "/", allow_redirects=False)
    assert not insecure_session_cookies(response), insecure_session_cookies(response)


@pytest.mark.parametrize("component", [requiring(c, c) for c in PUBLIC])
def test_foreign_origin_gets_no_cors_access(http: requests.Session, urls: dict[str, str], component: str) -> None:
    """Neither a preflight nor a GET from a foreign origin is allowed to read the root."""
    url = urls[component] + "/"
    preflight = http.options(url, headers={"Origin": FOREIGN_ORIGIN, "Access-Control-Request-Method": "GET"})
    get = http.get(url, headers={"Origin": FOREIGN_ORIGIN}, allow_redirects=False)
    for response in (preflight, get):
        assert not foreign_origin_allowed(response, FOREIGN_ORIGIN), describe(response)


@pytest.mark.parametrize("component", [requiring(c, c) for c in PUBLIC])
def test_certificate_is_valid_long_enough(podiumd_env: Environment, urls: dict[str, str], component: str) -> None:
    """The host's certificate is valid for it and for at least MIN_CERT_DAYS more days."""
    if not urls[component].startswith("https://"):
        pytest.skip(f"{component} is not served over https in this profile")
    days = days_valid(podiumd_env.peer_certificate(urls[component]), time.time())
    assert days >= MIN_CERT_DAYS, f"{component}'s certificate expires in {days:.0f} days"
