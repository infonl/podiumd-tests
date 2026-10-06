"""Unit tests for HTTP sessions in direct and host-header mode."""

from podiumd_tests.sessions import DEFAULT_TIMEOUT
from podiumd_tests.sessions import make_session


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
