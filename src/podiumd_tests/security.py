"""Security baseline of an environment: Keycloak realm settings, response headers, cookies, CORS, certificates.

The baseline is what podiumd's own Keycloak realm templates set since podiumd 4.6.0
(charts/podiumd/templates/keycloak-*-realm-config.yaml), and what a public web app sends.
"""

from __future__ import annotations

import re
import ssl

from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.json_data import section

if TYPE_CHECKING:
    import requests

    from podiumd_tests.json_data import JsonObject

# Longest access token podiumd's templates allow (their default is 60 s).
MAX_ACCESS_TOKEN_SECONDS = 300
# Most failed logins before Keycloak locks a user out.
MAX_FAILURE_FACTOR = 5
# Shortest password the realm may accept (podiumd realm 12, master 14).
MIN_PASSWORD_LENGTH = 12
# A certificate that expires sooner needs renewing now.
MIN_CERT_DAYS = 14
SESSION_COOKIE = re.compile(r"session|auth|token", re.IGNORECASE)


def realm_policy_gaps(realm: JsonObject) -> list[str]:
    """Where a realm representation falls short of podiumd's realm templates; empty when it does not."""
    gaps: list[str] = []
    if realm.get("bruteForceProtected") is not True:
        gaps.append("bruteForceProtected is off")
    elif not 0 < int(cast("int", realm.get("failureFactor") or 0)) <= MAX_FAILURE_FACTOR:
        gaps.append(f"failureFactor {realm.get('failureFactor')} (at most {MAX_FAILURE_FACTOR})")
    if int(cast("int", realm.get("accessTokenLifespan") or 0)) > MAX_ACCESS_TOKEN_SECONDS:
        gaps.append(f"accessTokenLifespan {realm.get('accessTokenLifespan')} s (at most {MAX_ACCESS_TOKEN_SECONDS})")
    if realm.get("revokeRefreshToken") is not True:
        gaps.append("revokeRefreshToken is off")
    gaps.extend(f"{e} is off" for e in ("eventsEnabled", "adminEventsEnabled") if realm.get(e) is not True)
    if realm.get("sslRequired") not in ("external", "all"):
        gaps.append(f"sslRequired {realm.get('sslRequired')!r} (external or all)")
    length = re.search(r"length\((\d+)\)", str(realm.get("passwordPolicy") or ""))
    if length is None or int(length[1]) < MIN_PASSWORD_LENGTH:
        gaps.append(f"passwordPolicy {realm.get('passwordPolicy')!r} (length at least {MIN_PASSWORD_LENGTH})")
    if not section(realm, "browserSecurityHeaders").get("strictTransportSecurity"):
        gaps.append("browserSecurityHeaders has no strictTransportSecurity")
    return gaps


def missing_security_headers(response: requests.Response) -> list[str]:
    """The baseline headers the response lacks: HSTS and nosniff always, frame protection on an HTML page."""
    headers = {k.lower(): v for k, v in response.headers.items()}
    missing: list[str] = []
    if response.url.startswith("https://") and "strict-transport-security" not in headers:
        missing.append("Strict-Transport-Security")
    # An app and its nginx may each send it: "nosniff, nosniff".
    if {v.strip().lower() for v in headers.get("x-content-type-options", "").split(",")} != {"nosniff"}:
        missing.append("X-Content-Type-Options: nosniff")
    html = headers.get("content-type", "").startswith("text/html")
    framed = "x-frame-options" in headers or "frame-ancestors" in headers.get("content-security-policy", "")
    if html and not framed:
        missing.append("X-Frame-Options or CSP frame-ancestors")
    return missing


def insecure_session_cookies(response: requests.Response) -> list[str]:
    """Session, auth or token cookies the response sets without Secure or HttpOnly."""
    found: list[str] = []
    for cookie in cast("list[str]", response.raw.headers.getlist("Set-Cookie")):
        name, _, rest = cookie.partition("=")
        flags = {f.strip().lower() for f in rest.split(";")[1:]}
        if SESSION_COOKIE.search(name) and not {"secure", "httponly"} <= flags:
            found.append(name)
    return found


def foreign_origin_allowed(response: requests.Response, origin: str) -> bool:
    """The response lets a page on origin read it: the origin echoed, or any origin with credentials."""
    allowed = response.headers.get("Access-Control-Allow-Origin")
    credentials = response.headers.get("Access-Control-Allow-Credentials", "").lower() == "true"
    return allowed == origin or (allowed == "*" and credentials)


def days_valid(certificate: JsonObject, now: float) -> float:
    """Days until a certificate from SSLSocket.getpeercert() expires."""
    return (ssl.cert_time_to_seconds(str(certificate["notAfter"])) - now) / 86400
