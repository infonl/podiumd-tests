"""Security baseline of an environment: Keycloak realm settings, response headers, cookies, CORS, certificates, TLS.

The baseline is what podiumd's own Keycloak realm templates set since podiumd 4.6.0
(charts/podiumd/templates/keycloak-*-realm-config.yaml), what a public web app sends, and NCSC's TLS guidelines 2.1.
"""

from __future__ import annotations

import re
import secrets
import ssl
import string

from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.json_data import section

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.json_data import JsonObject

# Longest access token podiumd's templates allow (their default is 60 s).
MAX_ACCESS_TOKEN_SECONDS = 300
# Most failed logins before Keycloak locks a user out.
MAX_FAILURE_FACTOR = 5
# Shortest password the realm may accept (podiumd realm 12, master 14).
MIN_PASSWORD_LENGTH = 12
# Length of the suite's own passwords where the realm asks less.
PASSWORD_LENGTH = 40
# Character classes a Keycloak passwordPolicy can count; the suite's passwords have one of each at least.
PASSWORD_CLASSES = {
    "upperCase": string.ascii_uppercase,
    "lowerCase": string.ascii_lowercase,
    "digits": string.digits,
    "specialChars": "-_.!*",
}
# A certificate that expires sooner needs renewing now.
MIN_CERT_DAYS = 14
SESSION_COOKIE = re.compile(r"session|auth|token", re.IGNORECASE)
# TLS 1.2 cipher suites NCSC's TLS guidelines 2.1 rate good or sufficient, as the ADR validator's security-tls ruleset
# lists them, by OpenSSL name (OpenSSL has no Camellia-GCM suites). Every TLS 1.3 suite OpenSSL offers is good.
NCSC_TLS12_CIPHERS = (
    "ECDHE-ECDSA-AES256-GCM-SHA384",
    "ECDHE-RSA-AES256-GCM-SHA384",
    "ECDHE-ECDSA-CHACHA20-POLY1305",
    "ECDHE-RSA-CHACHA20-POLY1305",
    "ECDHE-ECDSA-AES128-GCM-SHA256",
    "ECDHE-RSA-AES128-GCM-SHA256",
    "ECDHE-ECDSA-AES128-CCM",
    "ECDHE-ECDSA-AES256-CCM",
    "DHE-RSA-AES128-CCM",
    "DHE-RSA-AES256-CCM",
    "ECDHE-ECDSA-AES256-SHA384",
    "ECDHE-RSA-AES256-SHA384",
    "ECDHE-ECDSA-AES128-SHA256",
    "ECDHE-RSA-AES128-SHA256",
    "ECDHE-ECDSA-AES256-SHA",
    "ECDHE-RSA-AES256-SHA",
    "ECDHE-ECDSA-AES128-SHA",
    "ECDHE-RSA-AES128-SHA",
    "DHE-RSA-CHACHA20-POLY1305",
    "DHE-RSA-AES256-GCM-SHA384",
    "DHE-RSA-AES256-SHA256",
    "DHE-RSA-AES256-SHA",
    "DHE-RSA-AES128-GCM-SHA256",
    "DHE-RSA-AES128-SHA256",
    "DHE-RSA-AES128-SHA",
    "ECDHE-RSA-CAMELLIA128-SHA256",
    "ECDHE-RSA-CAMELLIA256-SHA384",
    "DHE-RSA-CAMELLIA128-SHA256",
    "DHE-RSA-CAMELLIA256-SHA",
    "DHE-RSA-CAMELLIA256-SHA256",
)
# TLS versions NCSC rates insufficient; OpenSSL 3 cannot offer SSL 3.0 at all.
OLD_TLS_VERSIONS = {ssl.TLSVersion.TLSv1: "TLSv1.0", ssl.TLSVersion.TLSv1_1: "TLSv1.1"}
# An unprefixed SemVer version, as the ADR validator's API-57 rule parses it (Masterminds semver, strict).
SEMVER = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?")


def _brute_force_gaps(realm: JsonObject) -> list[str]:
    if realm.get("bruteForceProtected") is not True:
        return ["bruteForceProtected is off"]
    if not 0 < int(cast("int", realm.get("failureFactor") or 0)) <= MAX_FAILURE_FACTOR:
        return [f"failureFactor {realm.get('failureFactor')} (at most {MAX_FAILURE_FACTOR})"]
    return []


def realm_policy_gaps(realm: JsonObject) -> list[str]:
    """Where a realm representation falls short of podiumd's realm templates; empty when it does not."""
    gaps = _brute_force_gaps(realm)
    if int(cast("int", realm.get("accessTokenLifespan") or 0)) > MAX_ACCESS_TOKEN_SECONDS:
        gaps.append(f"accessTokenLifespan {realm.get('accessTokenLifespan')} s (at most {MAX_ACCESS_TOKEN_SECONDS})")
    if realm.get("revokeRefreshToken") is not True:
        gaps.append("revokeRefreshToken is off")
    gaps.extend(
        f"{setting} is off" for setting in ("eventsEnabled", "adminEventsEnabled") if realm.get(setting) is not True
    )
    if realm.get("sslRequired") not in {"external", "all"}:
        gaps.append(f"sslRequired {realm.get('sslRequired')!r} (external or all)")
    length = re.search(r"length\((\d+)\)", str(realm.get("passwordPolicy") or ""))
    if length is None or int(length[1]) < MIN_PASSWORD_LENGTH:
        gaps.append(f"passwordPolicy {realm.get('passwordPolicy')!r} (length at least {MIN_PASSWORD_LENGTH})")
    if not section(realm, "browserSecurityHeaders").get("strictTransportSecurity"):
        gaps.append("browserSecurityHeaders has no strictTransportSecurity")
    return gaps


def _policy_rules(policy: str) -> dict[str, int]:
    """Return the counted rules of a Keycloak passwordPolicy, e.g. {"length": 12, "digits": 1}."""
    rules = dict(re.findall(r"(\w+)\((\d+)\)", policy))
    counted = {*PASSWORD_CLASSES, "length", "maxLength"}
    return {rule: int(count) for rule, count in rules.items() if rule in counted}


def _password(rules: dict[str, int], broken: str | None = None) -> str:
    """Return a random password that meets the rules, except the broken one, which it misses by one."""
    counts = {rule: rules.get(rule, 1) - (rule == broken) for rule in PASSWORD_CLASSES}
    picks = [rule for rule, count in counts.items() for _ in range(count)]
    chars = [secrets.choice(PASSWORD_CLASSES[rule]) for rule in picks]
    wanted = max(rules.get("length", 0), PASSWORD_LENGTH)
    length = rules["length"] - 1 if broken == "length" else wanted
    filler = PASSWORD_CLASSES["upperCase" if broken == "lowerCase" else "lowerCase"]
    chars += [secrets.choice(filler) for _ in range(length - len(chars))]
    return "".join(chars)[: rules.get("maxLength")]


def conforming_password(policy: str) -> str:
    """Return a random password that a realm with this passwordPolicy accepts."""
    return _password(_policy_rules(policy))


def policy_breaking_passwords(policy: str) -> dict[str, str]:
    """Per counted rule of the passwordPolicy, a password that breaks only that rule."""
    rules = _policy_rules(policy)
    return {rule: _password(rules, rule) for rule in rules if rule != "maxLength"}


def missing_security_headers(response: requests.Response) -> list[str]:
    """Return the baseline headers the response lacks: HSTS and nosniff always, frame protection on an HTML page.

    A redirect's HTML body is never rendered, so it cannot be framed: frame protection applies to 2xx only.
    """
    headers = {name.lower(): value for name, value in response.headers.items()}
    missing: list[str] = []
    if response.url.startswith("https://") and "strict-transport-security" not in headers:
        missing.append("Strict-Transport-Security")
    # An app and its nginx may each send it: "nosniff, nosniff".
    options = headers.get("x-content-type-options", "").split(",")
    if {option.strip().lower() for option in options} != {"nosniff"}:
        missing.append("X-Content-Type-Options: nosniff")
    html = response.ok and not response.is_redirect and headers.get("content-type", "").startswith("text/html")
    framed = "x-frame-options" in headers or "frame-ancestors" in headers.get("content-security-policy", "")
    if html and not framed:
        missing.append("X-Frame-Options or CSP frame-ancestors")
    return missing


def insecure_session_cookies(response: requests.Response) -> list[str]:
    """Session, auth or token cookies the response sets without Secure or HttpOnly."""
    found: list[str] = []
    for cookie in cast("list[str]", response.raw.headers.getlist("Set-Cookie")):
        name, _, rest = cookie.partition("=")
        flags = {flag.strip().lower() for flag in rest.split(";")[1:]}
        if SESSION_COOKIE.search(name) and not {"secure", "httponly"} <= flags:
            found.append(name)
    return found


def is_foreign_origin_allowed(response: requests.Response, origin: str) -> bool:
    """Return whether the response lets a page on origin read it: the origin echoed, or any origin with credentials."""
    allowed = response.headers.get("Access-Control-Allow-Origin")
    credentials = response.headers.get("Access-Control-Allow-Credentials", "").lower() == "true"
    return allowed == origin or (allowed == "*" and credentials)


def days_valid(certificate: JsonObject, now: float) -> float:
    """Days until a certificate from SSLSocket.getpeercert() expires."""
    return (ssl.cert_time_to_seconds(str(certificate["notAfter"])) - now) / 86400


def _cipher_string(excluded: list[str]) -> str:
    """Return an OpenSSL cipher string of every suite OpenSSL has, also below its security level, except excluded."""
    return ":".join(["ALL", "COMPLEMENTOFALL", *(f"!{name}" for name in excluded), "@SECLEVEL=0"])


def tls_below_ncsc(agreed: Callable[[ssl.TLSVersion, str], str | None]) -> list[str]:
    """Return the TLS versions and TLS 1.2 cipher suites a host agrees to that NCSC rates below sufficient.

    agreed(version, cipher string) is the cipher suite the host picks, None when it refuses (Environment.agreed_cipher).
    """
    found = [name for version, name in OLD_TLS_VERSIONS.items() if agreed(version, _cipher_string([]))]
    excluded: list[str] = list(NCSC_TLS12_CIPHERS)
    while cipher := agreed(ssl.TLSVersion.TLSv1_2, _cipher_string(excluded)):
        found.append(f"TLSv1.2 {cipher}")
        excluded.append(cipher)
    return found


def has_api_version(response: requests.Response) -> bool:
    """Return whether the response's API-Version header holds an unprefixed SemVer version (ADR API-57)."""
    return SEMVER.fullmatch(response.headers.get("API-Version", "")) is not None
