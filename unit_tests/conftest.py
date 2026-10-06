"""Offline fakes for the unit tests: no cluster, no network."""

import json
import subprocess

from collections.abc import Sequence
from dataclasses import dataclass

import pytest
import requests

from requests.adapters import HTTPAdapter

from podiumd_tests.config import parse_profile
from podiumd_tests.environment import Environment


class FakeRunner:
    """Answers commands by the first matching argv fragment; records every call."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []

    def __call__(self, args: Sequence[str], _timeout: int) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        line = " ".join(args)
        for fragment, (code, out) in self.answers.items():
            if fragment in line:
                return subprocess.CompletedProcess(list(args), code, out if code == 0 else "", "" if code == 0 else out)
        return subprocess.CompletedProcess(list(args), 1, "", f"no fake answer for: {line}")


@pytest.fixture
def fake_runner():
    return FakeRunner()


def make_profile(**overrides):
    raw = {
        "estate": "podiumd-infra",
        "allowed_tiers": ["smoke"],
        "kube": {"context": "ctx", "namespace": "podiumd"},
        "urls": {"openzaak": "https://openzaak.example.test", "keycloak-admin": "https://kc-admin.example.test"},
        "secrets": {},
    }
    raw.update(overrides)
    return parse_profile(raw, name="test-env")


@pytest.fixture
def profile_factory():
    return make_profile


def make_response(status=200, body=b"", url="https://app.example.test/", json_body=None):
    response = requests.Response()
    response.status_code = status
    response.url = url
    response._content = json.dumps(json_body).encode() if json_body is not None else body
    response.encoding = "utf-8"
    return response


@pytest.fixture
def response_factory():
    """Builds requests.Response objects without any network."""
    return make_response


@pytest.fixture
def env_factory(fake_runner):
    """Environment on fake_runner and an empty process environment; the profile defaults to make_profile()."""

    def build(profile=None, environ=None, runner=None):
        return Environment(profile or make_profile(), runner or fake_runner, environ=environ or {})

    return build


@dataclass(frozen=True)
class Sent:
    """A request as it left requests for the network: after adapters rewrote it."""

    method: str
    url: str
    headers: dict[str, str]
    timeout: object


@pytest.fixture
def fake_http(monkeypatch, response_factory):
    """Replace the network under requests. install({path: (status, json)}) returns the list of Sent requests.

    Unknown paths answer 404. The real adapters (e.g. host-header mode) still run.
    """
    sent = []

    def install(answers=None):
        def fake_send(_adapter, request, **kwargs):
            sent.append(Sent(request.method, request.url, dict(request.headers), kwargs.get("timeout")))
            status, json_body = (answers or {}).get(request.path_url.split("?")[0], (404, {"detail": "not found"}))
            response = response_factory(status=status, json_body=json_body, url=request.url)
            response.request = request
            return response

        monkeypatch.setattr(HTTPAdapter, "send", fake_send)
        return sent

    return install
