"""Unit tests for HTTP sessions in direct and host-header mode."""

from typing import TYPE_CHECKING
from typing import cast

import requests

from requests.cookies import MockRequest
from requests.cookies import create_cookie

from podiumd_tests.sessions import DEFAULT_TIMEOUT
from podiumd_tests.sessions import HostHeaderAdapter
from podiumd_tests.sessions import make_session

if TYPE_CHECKING:
    import urllib.request


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


def test_direct_mode_does_not_rewrite(fake_http):
    sent = fake_http()
    make_session({"openzaak": "https://openzaak.example.test"}).get("https://openzaak.example.test/")
    assert (sent[0].url, sent[0].headers.get("Host")) == ("https://openzaak.example.test/", None)


def test_a_session_without_cookies_accepts_none():
    # MockRequest is what requests itself hands to the cookie policy.
    request = cast(
        "urllib.request.Request", MockRequest(requests.Request("GET", "http://ok.test/admin/login/").prepare())
    )
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
