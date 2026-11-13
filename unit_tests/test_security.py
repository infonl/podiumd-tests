"""Unit tests for the security baseline checks."""

import re
import ssl

import pytest

from urllib3 import HTTPHeaderDict
from urllib3 import HTTPResponse

from podiumd_tests.security import conforming_password
from podiumd_tests.security import days_valid
from podiumd_tests.security import has_api_version
from podiumd_tests.security import insecure_session_cookies
from podiumd_tests.security import is_foreign_origin_allowed
from podiumd_tests.security import missing_security_headers
from podiumd_tests.security import policy_breaking_passwords
from podiumd_tests.security import realm_policy_gaps
from podiumd_tests.security import tls_below_ncsc

PODIUMD_REALM = {
    "bruteForceProtected": True,
    "failureFactor": 5,
    "accessTokenLifespan": 60,
    "revokeRefreshToken": True,
    "eventsEnabled": True,
    "adminEventsEnabled": True,
    "sslRequired": "external",
    "passwordPolicy": "length(12) and notUsername(undefined) and passwordHistory(5)",
    "browserSecurityHeaders": {"strictTransportSecurity": "max-age=31536000; includeSubDomains"},
}


def test_podiumds_realm_template_has_no_gaps():
    assert realm_policy_gaps(PODIUMD_REALM) == []


@pytest.mark.parametrize(
    ("change", "gap"),
    [
        ({"bruteForceProtected": False}, "bruteForceProtected is off"),
        ({"failureFactor": 30}, "failureFactor 30"),
        ({"accessTokenLifespan": 3600}, "accessTokenLifespan 3600 s"),
        ({"revokeRefreshToken": False}, "revokeRefreshToken is off"),
        ({"adminEventsEnabled": False}, "adminEventsEnabled is off"),
        ({"sslRequired": "none"}, "sslRequired 'none'"),
        ({"passwordPolicy": None}, "passwordPolicy None"),
        ({"passwordPolicy": "length(8)"}, "passwordPolicy 'length(8)'"),
        ({"browserSecurityHeaders": {}}, "browserSecurityHeaders has no strictTransportSecurity"),
    ],
)
def test_each_shortfall_is_a_gap(change, gap):
    gaps = realm_policy_gaps({**PODIUMD_REALM, **change})
    assert len(gaps) == 1
    assert gaps[0].startswith(gap)


def test_headers_of_a_good_html_page(response_factory):
    response = response_factory(url="https://app.example.test/")
    response.headers.update(
        {
            "Content-Type": "text/html; charset=utf-8",
            "Strict-Transport-Security": "max-age=31536000",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "frame-ancestors 'self'",
        }
    )
    assert missing_security_headers(response) == []


def test_frame_protection_only_matters_for_html(response_factory):
    response = response_factory(url="https://app.example.test/")
    response.headers.update({"Content-Type": "application/json", "X-Content-Type-Options": "nosniff"})
    assert missing_security_headers(response) == ["Strict-Transport-Security"]
    response.headers["Content-Type"] = "text/html"
    assert missing_security_headers(response) == ["Strict-Transport-Security", "X-Frame-Options or CSP frame-ancestors"]


def test_a_redirects_html_body_needs_no_frame_protection(response_factory):
    # e.g. OpenBao's / answers 307 to /ui/ with a small text/html body; a redirect is not rendered.
    response = response_factory(status=307, url="https://app.example.test/")
    response.headers.update(
        {
            "Content-Type": "text/html; charset=utf-8",
            "Location": "/ui/",
            "Strict-Transport-Security": "max-age=31536000",
            "X-Content-Type-Options": "nosniff",
        }
    )
    assert missing_security_headers(response) == []


def test_nosniff_sent_twice_counts(response_factory):
    response = response_factory(url="http://app.example.test/")
    response.headers["X-Content-Type-Options"] = "nosniff, nosniff"
    assert missing_security_headers(response) == []


def test_hsts_is_not_expected_over_http(response_factory):
    response = response_factory(url="http://app.example.test/")
    response.headers["X-Content-Type-Options"] = "nosniff"
    assert missing_security_headers(response) == []


def test_only_session_cookies_need_secure_and_httponly(response_factory):
    response = response_factory()
    headers = HTTPHeaderDict()
    for cookie in (
        "sessionid=a; Path=/; Secure; HttpOnly",
        "csrftoken=b; Path=/; Secure",
        "django_language=nl; Path=/",
        "AUTH_SESSION_ID=c; Path=/; secure; httponly",
    ):
        headers.add("Set-Cookie", cookie)
    response.raw = HTTPResponse(headers=headers)
    assert insecure_session_cookies(response) == ["csrftoken"]


@pytest.mark.parametrize(
    ("headers", "allowed"),
    [
        ({}, False),
        ({"Access-Control-Allow-Origin": "https://foreign.test"}, True),
        ({"Access-Control-Allow-Origin": "*"}, False),
        ({"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Credentials": "true"}, True),
        ({"Access-Control-Allow-Origin": "https://app.example.test"}, False),
    ],
)
def test_foreign_origin_allowed(response_factory, headers, allowed):
    response = response_factory()
    response.headers.update(headers)
    assert is_foreign_origin_allowed(response, "https://foreign.test") is allowed


def test_days_valid():
    expires = "Jan 31 00:00:00 2027 GMT"
    now = ssl.cert_time_to_seconds(expires) - 10 * 86400
    assert days_valid({"notAfter": expires}, now) == 10


POLICY = "length(12) and digits(2) and upperCase(1) and lowerCase(1) and specialChars(1) and notUsername(undefined)"


def counts(password):
    return {
        "length": len(password),
        "digits": sum(c.isdigit() for c in password),
        "upperCase": sum(c.isupper() for c in password),
        "lowerCase": sum(c.islower() for c in password),
        "specialChars": sum(not c.isalnum() for c in password),
    }


def meets(password, policy):
    rules = dict(re.findall(r"(\w+)\((\d+)\)", policy))
    return {rule for rule, count in counts(password).items() if rule in rules and count < int(rules[rule])}


def test_a_conforming_password_meets_every_rule():
    assert meets(conforming_password(POLICY), POLICY) == set()
    assert len(conforming_password("length(8)")) == 40
    assert len(conforming_password("length(60)")) == 60
    assert len(conforming_password("length(12) and maxLength(20)")) == 20


def test_each_breaking_password_breaks_only_its_rule():
    breaking = policy_breaking_passwords(POLICY)
    assert sorted(breaking) == ["digits", "length", "lowerCase", "specialChars", "upperCase"]
    for rule, password in breaking.items():
        assert meets(password, POLICY) == {rule}, rule


def test_a_policy_without_counted_rules_has_nothing_to_break():
    assert policy_breaking_passwords("notUsername(undefined) and passwordHistory(5)") == {}


@pytest.mark.parametrize(
    ("value", "valid"),
    [("1.5.1", True), ("0.6.0", True), ("2.0.0-rc.1+build.5", True), ("v1.5.1", False), ("1.5", False), ("", False)],
)
def test_has_api_version(response_factory, value, valid):
    response = response_factory()
    if value:
        response.headers["api-version"] = value
    assert has_api_version(response) is valid


def test_tls_below_ncsc_lists_old_versions_and_each_weak_tls12_suite():
    weak = ["AES256-SHA", "ECDHE-ARIA128-GCM-SHA256"]
    offered = []

    def agreed(version, ciphers):
        offered.append(ciphers)
        if version is not ssl.TLSVersion.TLSv1_2:
            return "AES128-SHA" if version is ssl.TLSVersion.TLSv1_1 else None
        excluded = set(re.findall(r"!([\w-]+)", ciphers))
        return next((name for name in weak if name not in excluded), None)

    assert tls_below_ncsc(agreed) == ["TLSv1.1", "TLSv1.2 AES256-SHA", "TLSv1.2 ECDHE-ARIA128-GCM-SHA256"]
    assert offered[0] == "ALL:COMPLEMENTOFALL:@SECLEVEL=0"
    assert "!ECDHE-RSA-AES128-GCM-SHA256" in offered[2]
    assert offered[-1].endswith("!AES256-SHA:!ECDHE-ARIA128-GCM-SHA256:@SECLEVEL=0")
