"""Unit tests for the inway's test identities and cases."""

import pytest

from podiumd_tests import inway
from podiumd_tests.process import run_checked
from podiumd_tests.process import run_process

# A self-signed certificate (CN=unit); its SHA-1 fingerprint from `openssl x509 -fingerprint -sha1`.
CERTIFICATE = """\
-----BEGIN CERTIFICATE-----
MIIBczCCARmgAwIBAgIUBH8WjIj9EDJPO54SpfmUMDRhfMIwCgYIKoZIzj0EAwIw
DzENMAsGA1UEAwwEdW5pdDAeFw0yNjExMTExNDMzMDFaFw0zNjExMDgxNDMzMDFa
MA8xDTALBgNVBAMMBHVuaXQwWTATBgcqhkjOPQIBBggqhkjOPQMBBwNCAAQN/As/
uuzffwHaP3aNX+MyNXBdn26A0hAQfjTSs0Mq9uVYXhyRpwZH7TcslCTRrklez4sG
jXqH91HJjXp+TMYCo1MwUTAdBgNVHQ4EFgQU5umUUA/cvui6/ijGnBjaZaD8kNcw
HwYDVR0jBBgwFoAU5umUUA/cvui6/ijGnBjaZaD8kNcwDwYDVR0TAQH/BAUwAwEB
/zAKBggqhkjOPQQDAgNIADBFAiEAzkcuUBUwilR9fmoiFqAtMQFo6tLzzD10GPoC
IUfsG20CIDu6CO68jBx+XMhJxs9GjQJoaF+TU9ZAjyNyeTCPimHj
-----END CERTIFICATE-----
"""
FINGERPRINT = "9e3788b6a507eb8b4bdb5466c92899583831bb26"
KEY = "-----BEGIN PRIVATE KEY-----\nnot-a-key\n-----END PRIVATE KEY-----\n"


def test_split_separates_the_certificate_from_the_key():
    assert inway.split(CERTIFICATE + KEY) == (CERTIFICATE, KEY)
    with pytest.raises(ValueError, match="no private key"):
        inway.split(CERTIFICATE)


def test_fingerprint_is_the_lower_case_sha1_of_the_der_certificate():
    assert inway.fingerprint(CERTIFICATE) == FINGERPRINT


def test_identity_files_are_written_private(tmp_path):
    certificate, key = inway.identity_files(CERTIFICATE + KEY, "partner-b", tmp_path)
    assert (tmp_path / "partner-b.pem").read_text() == CERTIFICATE
    assert (tmp_path / "partner-b.key").read_text() == KEY
    assert (certificate, key) == (str(tmp_path / "partner-b.pem"), str(tmp_path / "partner-b.key"))
    assert (tmp_path / "partner-b.key").stat().st_mode & 0o777 == 0o600


def test_secret_name_of_an_identity():
    assert inway.secret_name("partner-a") == "inway_partner_a"


def test_forged_headers_claim_the_allowed_consumers_fingerprint():
    headers = inway.forged_headers(CERTIFICATE + KEY)
    assert headers == {"X-Client-Cert-Verification": "SUCCESS", "X-Client-Cert-Fingerprint": FINGERPRINT}


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [(401, '{"error": "client_certificate_not_verified"}', True), (301, "", True), (200, "Hello!Frank", False)],
)
def test_is_expected_needs_a_listed_status_with_its_body_part(status, body, expected):
    case = next(case for case in inway.CASES if case.plain_http)
    assert inway.is_expected(case, status, body) is expected


def test_cases_run_the_allowed_consumer_last():
    assert inway.CASES[-1].identity == inway.ALLOWED


def _identity(directory):
    """A CA and an identity it signed, made with the real openssl."""
    ca = directory / "ca"
    command = ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", f"{ca}.key", "-out", f"{ca}.crt"]
    run_checked(run_process, [*command, "-subj", "/CN=unit-ca", "-days", "1"], 30)
    return inway.make_identity(run_process, ca, directory, "partner-x")


def test_make_identity_signs_a_certificate_with_the_client_ca(tmp_path):
    certificate, key = inway.split(_identity(tmp_path))
    issuer = run_checked(run_process, ["openssl", "x509", "-noout", "-issuer", "-subject"], 30, stdin=certificate)
    assert "CN=unit-ca" in issuer
    assert "CN=partner-x" in issuer
    assert key.startswith("-----BEGIN PRIVATE KEY-----")
    assert not list(tmp_path.glob("*.srl"))


def test_make_identity_without_a_client_ca_is_self_signed(tmp_path):
    certificate, _ = inway.split(inway.make_identity(run_process, None, tmp_path, "partner-a"))
    names = run_checked(run_process, ["openssl", "x509", "-noout", "-issuer", "-subject"], 30, stdin=certificate)
    assert names.count("CN=partner-a") == 2
