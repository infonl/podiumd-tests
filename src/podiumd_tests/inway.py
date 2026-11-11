"""Frank!Gateway's inway behind the edge's client-certificate check (mTLS), and its test consumers.

The edge verifies the client certificate and passes it on as X-Client-Cert-* headers; the inway's
openbao-consumer-auth looks the fingerprint up in OpenBao (secret/frankgateway/consumers) and the route allows
partner-a only. The inway caches the consumers for 300 s, so a test runs its cases worst first: a cached success
cannot then answer a later denial.
"""

from __future__ import annotations

import hashlib
import ssl

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# The inway route to the fg-echo test upstream; fg-echo answers this greeting.
ECHO_PATH = "/echo/hello"
GREETING = "Hello!Frank"
ALLOWED = "partner-a"
# Signed by the edge's client CA; partner-a and partner-b are registered consumers.
IDENTITIES = ("partner-a", "partner-b", "partner-c")
PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----"


@dataclass(frozen=True)
class Case:
    """One request to the inway and the answers (status, body part) it may get."""

    name: str
    what: str
    identity: str
    answers: tuple[tuple[int, str], ...]
    # Sends partner-a's fingerprint as verified client-certificate headers.
    forged: bool = False
    plain_http: bool = False


# Worst first, as the consumer cache requires.
CASES = (
    Case(
        "forged-headers-unknown-certificate",
        "hand-written client certificate headers next to a certificate nobody onboarded",
        "partner-c",
        ((401, "unknown_client_certificate"),),
        forged=True,
    ),
    # 301 where the edge redirects http to https; never an answer of the inway.
    Case(
        "forged-headers-over-http",
        "hand-written client certificate headers over http",
        "",
        ((401, "client_certificate_not_verified"), (301, "")),
        forged=True,
        plain_http=True,
    ),
    Case(
        "unknown-certificate",
        "a valid certificate nobody onboarded",
        "partner-c",
        ((401, "unknown_client_certificate"),),
    ),
    Case("not-allowed", "a consumer the route does not allow", "partner-b", ((403, "consumer_not_allowed"),)),
    Case("allowed", "the allowed consumer", ALLOWED, ((200, GREETING),)),
)


def secret_name(identity: str) -> str:
    """Return the secret that holds the identity's certificate PEM followed by its key PEM."""
    return f"inway_{identity.replace('-', '_')}"


def split(identity_pem: str) -> tuple[str, str]:
    """Return the certificate PEM and the key PEM of an identity."""
    certificate, marker, key = identity_pem.partition(PRIVATE_KEY)
    if not marker:
        msg = "identity has no private key PEM"
        raise ValueError(msg)
    return f"{certificate.strip()}\n", f"{marker}{key.rstrip()}\n"


def fingerprint(certificate_pem: str) -> str:
    """Return the certificate's lower-case SHA-1 hex fingerprint, as the edge sends it and OpenBao lists it."""
    return hashlib.sha1(ssl.PEM_cert_to_DER_cert(certificate_pem), usedforsecurity=False).hexdigest()


def identity_files(identity_pem: str, name: str, directory: Path) -> tuple[str, str]:
    """Write an identity's certificate and key to directory; their paths, for requests' cert."""
    pair = (directory / f"{name}.pem", directory / f"{name}.key")
    for path, text in zip(pair, split(identity_pem), strict=True):
        path.write_text(text)
        path.chmod(0o600)
    return str(pair[0]), str(pair[1])


def forged_headers(allowed_pem: str) -> dict[str, str]:
    """Headers that claim the allowed consumer's certificate was verified, as only the edge may send them."""
    certificate, _ = split(allowed_pem)
    return {"X-Client-Cert-Verification": "SUCCESS", "X-Client-Cert-Fingerprint": fingerprint(certificate)}


def is_expected(case: Case, status: int, body: str) -> bool:
    """Return whether the case accepts this answer."""
    return any(status == expected and part in body for expected, part in case.answers)
