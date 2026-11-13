"""Frank!Gateway's inway behind the edge's client-certificate check (mTLS), and its test consumers.

The edge passes the client certificate on as X-Client-Cert-* headers, verified against its client CA or, in
passthrough mode (IN-3287), unchecked; the inway's openbao-consumer-auth looks the fingerprint up in OpenBao
(secret/frankgateway/consumers) and the route allows partner-a only. The inway caches the consumers for 300 s, so
a test runs its cases worst first: a cached success cannot then answer a later denial.
"""

from __future__ import annotations

import hashlib
import secrets
import ssl

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from podiumd_tests.process import run_checked

if TYPE_CHECKING:
    from podiumd_tests.process import Runner

# The inway route to the fg-echo test upstream; fg-echo answers this greeting.
ECHO_PATH = "/echo/hello"
GREETING = "Hello!Frank"
ALLOWED = "partner-a"
# Signed by the edge's client CA; partner-a and partner-b are registered consumers.
IDENTITIES = ("partner-a", "partner-b", "partner-c")
PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----"
OPENSSL_TIMEOUT = 30
# The status of a TLS handshake the edge refuses.
TLS_REFUSED = 0


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
    # A self-signed certificate for the identity's name instead of its stored one.
    self_signed: bool = False


# Worst first, as the consumer cache requires.
CASES = (
    Case(
        "forged-headers-unknown-certificate",
        "hand-written client certificate headers next to a certificate nobody onboarded",
        "partner-c",
        ((401, "unknown_client_certificate"),),
        forged=True,
    ),
    # 301 where the edge redirects http to https; never an answer of the inway. client_certificate_required in
    # passthrough mode, where the inway checks no verification header.
    Case(
        "forged-headers-over-http",
        "hand-written client certificate headers over http",
        "",
        ((401, "client_certificate_not_verified"), (401, "client_certificate_required"), (301, "")),
        forged=True,
        plain_http=True,
    ),
    # client_certificate_required in passthrough mode; client_certificate_not_verified, 400 or a refused handshake where
    # the edge checks for a certificate.
    Case(
        "no-certificate",
        "no client certificate",
        "",
        (
            (401, "client_certificate_required"),
            (401, "client_certificate_not_verified"),
            (400, "No required SSL certificate"),
            (TLS_REFUSED, ""),
        ),
    ),
    # 401 in passthrough mode; 400 or a refused handshake where the edge checks the certificate against its client CA.
    Case(
        "untrusted-certificate",
        "a self-signed certificate in the allowed consumer's name",
        ALLOWED,
        ((401, "unknown_client_certificate"), (400, "SSL certificate"), (TLS_REFUSED, "")),
        self_signed=True,
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
    """Headers that claim the allowed consumer's certificate was verified, as only the edge may send them.

    X-Client-Cert-Verification only counts where the inway route has a verificationHeader (not in passthrough mode).
    """
    certificate, _ = split(allowed_pem)
    return {"X-Client-Cert-Verification": "SUCCESS", "X-Client-Cert-Fingerprint": fingerprint(certificate)}


def is_expected(case: Case, status: int, body: str) -> bool:
    """Return whether the case accepts this answer."""
    return any(status == expected and part in body for expected, part in case.answers)


def make_identity(runner: Runner, client_ca: Path | None, directory: Path, name: str) -> str:
    """Return a new key and a certificate for CN=name signed by the client CA, as certificate PEM + key PEM.

    Without a client CA the certificate is self-signed.
    """
    key, request, certificate = (str(directory / f"{name}.{suffix}") for suffix in ("key", "csr", "pem"))
    new_key = ["openssl", "req", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-subj", f"/CN={name}"]
    if client_ca is None:
        run_checked(runner, [*new_key, "-x509", "-days", "1", "-out", certificate], OPENSSL_TIMEOUT)
    else:
        signed = ["openssl", "x509", "-req", "-in", request, "-CA", f"{client_ca}.crt", "-CAkey", f"{client_ca}.key"]
        # A serial of its own: -CAcreateserial would write a serial file next to the CA, in the owner's directory.
        serial = f"0x{secrets.token_hex(16)}"
        run_checked(runner, [*new_key, "-new", "-out", request], OPENSSL_TIMEOUT)
        run_checked(runner, [*signed, "-set_serial", serial, "-days", "365", "-out", certificate], OPENSSL_TIMEOUT)
    return Path(certificate).read_text(encoding="ascii") + Path(key).read_text(encoding="ascii")
