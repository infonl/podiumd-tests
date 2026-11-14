"""Unit tests for HTTP sessions in direct and host-header mode."""

import ssl

from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING
from typing import cast

import pytest
import requests

from requests.cookies import MockRequest
from requests.cookies import create_cookie

from podiumd_tests import sessions
from podiumd_tests.sessions import DEFAULT_TIMEOUT
from podiumd_tests.sessions import HostHeaderAdapter
from podiumd_tests.sessions import make_session

if TYPE_CHECKING:
    from urllib.request import Request


def test_host_header_mode_rewrites_profile_hosts(fake_http):
    sent = fake_http()
    session = make_session({"zac": "http://zac.local"}, ingress_ip="10.0.0.5")
    session.get("http://zac.local/rest/health?x=1")
    assert [(r.url, r.headers.get("Host"), r.timeout) for r in sent] == [
        ("http://10.0.0.5/rest/health?x=1", "zac.local", DEFAULT_TIMEOUT)
    ]


def test_host_header_mode_restores_the_url_for_redirects_and_asserts(fake_http):
    fake_http()
    session = make_session({"zac": "http://zac.local"}, ingress_ip="10.0.0.5")
    response = session.get("http://zac.local/login")
    assert response.url == "http://zac.local/login"
    assert response.request.url == "http://zac.local/login"
    assert "Host" not in response.request.headers


def test_host_header_mode_leaves_other_hosts_alone(fake_http):
    sent = fake_http()
    session = make_session({"zac": "http://zac.local"}, ingress_ip="10.0.0.5")
    session.get("https://example.test/", timeout=3)
    assert [(r.url, r.headers.get("Host"), r.timeout) for r in sent] == [("https://example.test/", None, 3)]


def test_host_header_mode_reaches_a_port_forwarded_url_directly(fake_http):
    sent = fake_http()
    session = make_session({"api-proxy": "http://127.0.0.1:4711"}, ingress_ip="10.0.0.5")
    session.get("http://127.0.0.1:4711/haalcentraal", timeout=3)
    assert [(r.url, r.headers.get("Host")) for r in sent] == [("http://127.0.0.1:4711/haalcentraal", None)]


def test_direct_mode_does_not_rewrite(fake_http):
    sent = fake_http()
    make_session({"openzaak": "https://openzaak.example.test"}).get("https://openzaak.example.test/")
    assert (sent[0].url, sent[0].headers.get("Host")) == ("https://openzaak.example.test/", None)


def test_a_session_without_cookies_accepts_none():
    # MockRequest is what requests itself hands to the cookie policy.
    request = cast("Request", MockRequest(requests.Request("GET", "http://ok.test/admin/login/").prepare()))
    cookie = create_cookie("sessionid", "abc", domain="ok.test")
    assert not make_session({"openklant": "http://ok.test"}, cookies=False).cookies.get_policy().set_ok(cookie, request)
    assert make_session({"openklant": "http://ok.test"}).cookies.get_policy().set_ok(cookie, request)


def test_https_through_the_ingress_ip_verifies_the_profile_host():
    adapter = HostHeaderAdapter({"zac.local"}, "10.0.0.5")
    request = requests.Request("GET", "https://10.0.0.5/", headers={"Host": "zac.local"}).prepare()
    host_params, pool_kwargs = adapter.build_connection_pool_key_attributes(request, verify=True)
    assert host_params["host"] == "10.0.0.5"
    assert (pool_kwargs.get("server_hostname"), pool_kwargs.get("assert_hostname")) == ("zac.local", "zac.local")


def test_session_verifies_with_the_given_ca_bundle():
    assert make_session({"zac": "https://zac.local"}, verify="ca.pem").verify == "ca.pem"


class FakeTls:
    """A TLS socket that records what is sent and answers with a fixed reply, or times out."""

    def __init__(self, reply: bytes | None) -> None:
        self.reply: bytes | None = reply
        self.sent: bytes = b""
        self.timeout: float = 0

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def settimeout(self, seconds: float) -> None:
        self.timeout = seconds

    def recv(self, _size: int) -> bytes:
        if self.reply is None:
            raise TimeoutError
        return self.reply


@pytest.mark.parametrize(("reply", "status"), [(b"HTTP/1.1 413 Request Entity Too Large\r\n", 413), (None, None)])
def test_announced_body_status_reads_the_status_or_none(monkeypatch, reply, status):
    fake = FakeTls(reply)

    @contextmanager
    def tls(*_args):
        yield fake

    monkeypatch.setattr(sessions, "_tls", tls)
    assert sessions.announced_body_status("https://zac.test/rest/x", 10**9) == status
    assert fake.sent.startswith(b"POST /rest/x HTTP/1.1\r\nHost: zac.test\r\nContent-Length: 1000000000\r\n")
    head, body = fake.sent.split(b"\r\n\r\n")
    assert (head.endswith(b"application/octet-stream"), body) == (True, b"x" * 1024)


def _reason_error(reason):
    error = ssl.SSLError(1, reason)
    error.reason = reason
    return error


def _fake_tls(monkeypatch, outcome):
    """Make sessions._tls yield a socket that agreed to the outcome cipher, or raise the outcome; the contexts used."""
    contexts = []

    @contextmanager
    def tls(_url, _ip, _ca, context):
        contexts.append(context)
        if isinstance(outcome, BaseException):
            raise outcome
        yield SimpleNamespace(cipher=lambda: outcome)

    monkeypatch.setattr(sessions, "_tls", tls)
    return contexts


@pytest.mark.parametrize(
    ("outcome", "cipher"),
    [
        (("ECDHE-RSA-AES128-GCM-SHA256", "TLSv1.2", 128), "ECDHE-RSA-AES128-GCM-SHA256"),
        (_reason_error("TLSV1_ALERT_PROTOCOL_VERSION"), None),
        (ConnectionResetError(), None),
    ],
)
def test_agreed_cipher_reads_the_cipher_or_none(monkeypatch, outcome, cipher):
    contexts = _fake_tls(monkeypatch, outcome)
    assert sessions.agreed_cipher("https://zac.test/", ssl.TLSVersion.TLSv1_1, "ALL:@SECLEVEL=0") == cipher
    assert contexts[0].maximum_version is ssl.TLSVersion.TLSv1_1


def test_agreed_cipher_is_none_when_the_cipher_string_leaves_none():
    assert sessions.agreed_cipher("https://zac.test/", ssl.TLSVersion.TLSv1_2, "!ALL") is None


@pytest.mark.parametrize(
    "error", [_reason_error("NO_PROTOCOLS_AVAILABLE"), ssl.SSLCertVerificationError(1, "certificate verify failed")]
)
def test_agreed_cipher_raises_what_is_no_refusal(monkeypatch, error):
    _fake_tls(monkeypatch, error)
    with pytest.raises(type(error)):
        sessions.agreed_cipher("https://zac.test/", ssl.TLSVersion.TLSv1, "ALL")
