"""Frank!Gateway's inway lets in only the consumers OpenBao lists and the route allows, by their client certificate.

The cases run in this order on one worker (xdist group): worst first, because the inway caches consumers for 300 s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import pytest
import requests

from podiumd_tests.inway import ALLOWED
from podiumd_tests.inway import CASES
from podiumd_tests.inway import ECHO_PATH
from podiumd_tests.inway import IDENTITIES
from podiumd_tests.inway import TLS_REFUSED
from podiumd_tests.inway import forged_headers
from podiumd_tests.inway import identity_files
from podiumd_tests.inway import is_expected
from podiumd_tests.inway import make_identity
from podiumd_tests.inway import secret_name
from podiumd_tests.process import run_process

if TYPE_CHECKING:
    from pathlib import Path

    from podiumd_tests.credentials import SecretResolver
    from podiumd_tests.inway import Case

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("inway"),
    pytest.mark.xdist_group("inway"),
    pytest.mark.source(
        "external podiumd-infra src/podiumd_infra/waf_check.py (waf-mtls-check)",
        "The aag rig's client-certificate test: the inway admits a consumer by the certificate the edge verified.",
    ),
]

# The ports an FSC inway must answer on (FSC test suite, Inway-Port-1).
FSC_PORTS = (443, 8443)


@pytest.fixture(name="identities")
def fixture_identities(credentials: SecretResolver) -> None:
    """Skips unless the profile or bootstrap has the inway's test identities."""
    missing = [name for name in IDENTITIES if not credentials.is_configured(secret_name(name))]
    if missing:
        pytest.skip(f"inway test identities missing: {', '.join(missing)}")


@pytest.mark.usefixtures("identities")
@pytest.mark.parametrize("case", [pytest.param(case, id=case.name) for case in CASES])
@pytest.mark.source(
    "external commonground/standards/fsc test-suite/inway.md Inway-Incoming-Request-4",
    "The inway denies a request whose certificate its trust anchor did not sign.",
)
@pytest.mark.scenario("""
    Given consumers partner-a and partner-b in OpenBao, and an inway route that allows partner-a only
    When a caller calls the route without a certificate, with its own, a self-signed one, or hand-written headers
    Then partner-a gets the upstream's answer
    And partner-b is refused as not allowed, an unknown or self-signed certificate as unknown
    And a request without a client certificate is refused
    And hand-written certificate headers never count as a verified certificate
""")
def test_inway_admits_only_the_allowed_consumer(
    http: requests.Session,
    urls: dict[str, str],
    credentials: SecretResolver,
    tmp_path: Path,
    case: Case,
) -> None:
    """The inway's answer to one consumer case of podiumd-infra's waf-mtls-check."""
    url = urls["inway"] + ECHO_PATH
    if case.plain_http:
        url = url.replace("https://", "http://", 1)
    headers = forged_headers(credentials.get(secret_name(ALLOWED))) if case.forged else {}
    certificate = None
    if case.identity:
        pem = make_identity(run_process, None, tmp_path, case.identity) if case.self_signed else None
        certificate = identity_files(pem or credentials.get(secret_name(case.identity)), case.identity, tmp_path)
    try:
        response = http.get(url, headers=headers, cert=certificate, allow_redirects=False)
    except requests.exceptions.SSLError as exc:
        status, body = TLS_REFUSED, str(exc)
    else:
        status, body = response.status_code, response.text
    accepted = " or ".join(f"{expected} {part}".strip() for expected, part in case.answers)
    assert is_expected(case, status, body), f"{case.what}: {status} {body[:200]}, expected {accepted}"


@pytest.mark.source(
    "external commonground/standards/fsc test-suite/inway.md Inway-Port-1",
    "An inway accepts requests on port 443 or 8443.",
)
@pytest.mark.scenario("""
    Given the inway URL partners call
    Then it is https on port 443 or 8443
""")
def test_inway_url_uses_an_fsc_port(urls: dict[str, str]) -> None:
    """The inway's URL is https on port 443 or 8443."""
    parts = urlsplit(urls["inway"])
    assert parts.scheme == "https", f"inway URL {urls['inway']} is not https"
    assert (parts.port or FSC_PORTS[0]) in FSC_PORTS, f"inway URL {urls['inway']} is not on port 443 or 8443"
