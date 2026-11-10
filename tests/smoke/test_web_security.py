"""Security baseline of every public host: headers, session cookies, CORS and the TLS certificate.

Neither estate's edge adds security headers, so each app must send its own.
"""

from __future__ import annotations

import time

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.components import HOSTED
from podiumd_tests.pytest_plugin import public_url
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.responses import describe
from podiumd_tests.security import MIN_CERT_DAYS
from podiumd_tests.security import days_valid
from podiumd_tests.security import insecure_session_cookies
from podiumd_tests.security import is_foreign_origin_allowed
from podiumd_tests.security import missing_security_headers
from podiumd_tests.workloads import is_chart_older_than

if TYPE_CHECKING:
    import requests

    from _pytest.mark.structures import ParameterSet

    from podiumd_tests.environment import Environment

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.source(
        "podiumd-tests",
        "Security baseline of every public host: security headers, secure session cookies, no foreign CORS, valid TLS.",
    ),
]

# Mailpit is minikube's mail sink; api-proxy and the Frank!Gateway outway have no public host on the estates.
NOT_PUBLIC = ("mailpit", "api-proxy", "frankgateway")
PUBLIC = sorted(set(HOSTED) - set(NOT_PUBLIC))
FOREIGN_ORIGIN = "https://ptest-foreign.example.invalid"
# Apps that send none or part of the headers themselves; xfail without strict, as an edge may add them.
HEADER_GAPS = {
    "pabc": "[pabc-1] PABC sends no HSTS, nosniff or frame protection",
    "ita": "[ita-2] ITA sends no HSTS and no nosniff",
    "openarchiefbeheer": "[open-archiefbeheer-5] Open Archiefbeheer sends no HSTS and no nosniff",
    "openformulieren": "[open-formulieren-3] Open Formulieren sends no HSTS",
    "grafana": "[podiumd-chart-1] Grafana sends no HSTS (its strict_transport_security setting is off)",
    "openbeheer": "[open-beheer-1] Open Beheer 0.9.1 sends no HSTS and no nosniff on its frontend",
    "omc": "[omc-3] OMC 2.3.1 sends no HSTS and no nosniff",
}


def headers_param(component: str) -> ParameterSet:
    """The component as a parameter, xfail where HEADER_GAPS knows it lacks headers."""
    gap = HEADER_GAPS.get(component)
    marks = [pytest.mark.xfail(strict=False, reason=f"{gap}; not yet reported upstream")] if gap else []
    return requiring(component, component, marks=marks)


@pytest.mark.parametrize("component", [headers_param(c) for c in PUBLIC])
@pytest.mark.scenario("""
    When the root of each public host is opened
    Then it sends HSTS and nosniff headers
    And an HTML page also sends frame protection
""")
def test_security_headers(
    request: pytest.FixtureRequest,
    http: requests.Session,
    podiumd_env: Environment,
    urls: dict[str, str],
    component: str,
) -> None:
    """The root sends HSTS and nosniff, and frame protection when it is an HTML page."""
    if component == "openbao" and is_chart_older_than(podiumd_env, (4, 10, 1)):
        reason = "[podiumd-chart-23] podiumd before 4.10.1 sets no custom_response_headers for OpenBao: no nosniff"
        request.applymarker(pytest.mark.xfail(strict=False, reason=f"{reason} (helm-charts #664)"))
    response = http.get(f"{public_url(podiumd_env, urls, component)}/", allow_redirects=False)
    assert not missing_security_headers(response), f"{describe(response)} lacks {missing_security_headers(response)}"


@pytest.mark.parametrize("component", [requiring(c, c) for c in PUBLIC])
@pytest.mark.scenario("""
    When the root of each public host is opened
    Then every session, auth or token cookie it sets is Secure and HttpOnly
""")
def test_session_cookies_are_secure(
    http: requests.Session, podiumd_env: Environment, urls: dict[str, str], component: str
) -> None:
    """Session, auth and token cookies the root sets are Secure and HttpOnly."""
    response = http.get(f"{public_url(podiumd_env, urls, component)}/", allow_redirects=False)
    assert not insecure_session_cookies(response), insecure_session_cookies(response)


@pytest.mark.parametrize("component", [requiring(c, c) for c in PUBLIC])
@pytest.mark.scenario("""
    Given a page on a foreign origin
    When it sends a CORS preflight and a GET to the root of each public host
    Then the host allows neither to be read by that origin
""")
def test_foreign_origin_gets_no_cors_access(
    http: requests.Session, podiumd_env: Environment, urls: dict[str, str], component: str
) -> None:
    """Neither a preflight nor a GET from a foreign origin is allowed to read the root."""
    url = f"{public_url(podiumd_env, urls, component)}/"
    preflight = http.options(url, headers={"Origin": FOREIGN_ORIGIN, "Access-Control-Request-Method": "GET"})
    get = http.get(url, headers={"Origin": FOREIGN_ORIGIN}, allow_redirects=False)
    for response in (preflight, get):
        assert not is_foreign_origin_allowed(response, FOREIGN_ORIGIN), describe(response)


@pytest.mark.parametrize("component", [requiring(c, c) for c in PUBLIC])
@pytest.mark.scenario("""
    When the TLS certificate of each public host is read
    Then it is valid for at least the minimum number of days ahead
""")
def test_certificate_is_valid_long_enough(podiumd_env: Environment, urls: dict[str, str], component: str) -> None:
    """The host's certificate is valid for it and for at least MIN_CERT_DAYS more days."""
    url = public_url(podiumd_env, urls, component)
    if not url.startswith("https://"):
        pytest.skip(f"{component} is not served over https in this profile")
    days = days_valid(podiumd_env.peer_certificate(url), time.time())
    assert days >= MIN_CERT_DAYS, f"{component}'s certificate expires in {days:.0f} days"
