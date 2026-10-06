"""Unit tests for HTTP sessions in direct and host-header mode."""

import requests

from requests.adapters import HTTPAdapter

from podiumd_tests.sessions import DEFAULT_TIMEOUT
from podiumd_tests.sessions import make_session


def capture_sends(monkeypatch):
    sent = []

    def fake_send(self, request, **kwargs):
        sent.append((request.url, request.headers.get("Host"), kwargs.get("timeout")))
        response = requests.Response()
        response.status_code = 200
        response.request = request
        return response

    monkeypatch.setattr(HTTPAdapter, "send", fake_send)
    return sent


def test_host_header_mode_rewrites_profile_hosts(monkeypatch):
    sent = capture_sends(monkeypatch)
    session = make_session({"zac": "http://zac.local"}, ingress_ip="10.0.0.5")
    session.get("http://zac.local/rest/health?x=1")
    assert sent == [("http://10.0.0.5/rest/health?x=1", "zac.local", DEFAULT_TIMEOUT)]


def test_host_header_mode_restores_the_url_for_redirects_and_asserts(monkeypatch):
    capture_sends(monkeypatch)
    session = make_session({"zac": "http://zac.local"}, ingress_ip="10.0.0.5")
    response = session.get("http://zac.local/login")
    assert response.url == "http://zac.local/login"
    assert response.request.url == "http://zac.local/login"
    assert "Host" not in response.request.headers


def test_host_header_mode_leaves_other_hosts_alone(monkeypatch):
    sent = capture_sends(monkeypatch)
    session = make_session({"zac": "http://zac.local"}, ingress_ip="10.0.0.5")
    session.get("https://example.test/", timeout=3)
    assert sent == [("https://example.test/", None, 3)]


def test_direct_mode_does_not_rewrite(monkeypatch):
    sent = capture_sends(monkeypatch)
    make_session({"openzaak": "https://openzaak.example.test"}).get("https://openzaak.example.test/")
    assert sent[0][:2] == ("https://openzaak.example.test/", None)
