"""Offline fakes for the unit tests: no cluster, no network."""

import json
import subprocess

from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
import requests

from playwright.sync_api import Error as PlaywrightError
from requests.adapters import HTTPAdapter

from podiumd_tests.config import parse_profile
from podiumd_tests.environment import Environment


class FakeRunner:
    """Answers commands by the first matching argv fragment; records every call."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []
        self.stdins = []

    def __call__(
        self, args: Sequence[str], _timeout: int, stdin: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        self.stdins.append(stdin)
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
    body: object = None


@pytest.fixture
def fake_http(monkeypatch, response_factory):
    """Replace the network under requests. install({path: (status, json)}) returns the list of Sent requests.

    A key "METHOD path" answers only that method; a plain path answers any method; unknown paths
    answer 404. The real adapters (host-header mode) still run.
    """
    sent = []

    def install(answers=None):
        def fake_send(_adapter, request, **kwargs):
            sent.append(Sent(request.method, request.url, dict(request.headers), kwargs.get("timeout"), request.body))
            path = request.path_url.split("?")[0]
            table = answers or {}
            status, json_body = table.get(f"{request.method} {path}", table.get(path, (404, {"detail": "not found"})))
            response = response_factory(status=status, json_body=json_body, url=request.url)
            response.request = request
            return response

        monkeypatch.setattr(HTTPAdapter, "send", fake_send)
        return sent

    return install


class FakeLocator:
    """A Playwright locator that records its actions on the FakePage; key names what it locates."""

    def __init__(self, page, key):
        self.page = page
        self.key = key

    @property
    def first(self):
        return self

    def locator(self, selector):
        return FakeLocator(self.page, f"{self.key} {selector}")

    def get_by_role(self, role, name):
        return FakeLocator(self.page, f"{self.key} {role}:{name}")

    def fill(self, value):
        self.page.actions.append(("fill", self.key, value))

    def click(self):
        self.page.actions.append(("click", self.key))

    def select_option(self, label):
        self.page.actions.append(("select", self.key, label))

    def set_input_files(self, files):
        self.page.actions.append(("files", self.key, files))

    def inner_text(self):
        return self.page.texts[self.key]

    def input_value(self):
        return self.page.texts[self.key]

    def count(self):
        return int(self.is_visible())

    def is_visible(self):
        return self.key in self.page.texts


class FakePage:  # pylint: disable=too-many-instance-attributes  # one per Page feature the helpers use
    """A Playwright page without a browser: goto sets url; wait_for_url moves to the next of landings.

    texts maps the keys of the visible elements to their text; each goto raises the next of errors first.
    """

    def __init__(self, url="about:blank", texts=None, landings=(), evaluated=(), cookies=(), errors=()):
        self.url = url
        self.errors = list(errors)
        self.texts = texts or {}
        self.landings = list(landings)
        self.evaluated = list(evaluated)
        self.actions = []
        self.waits = []
        self.context = SimpleNamespace(cookies=lambda: list(cookies))

    def locator(self, selector):
        return FakeLocator(self, selector)

    def get_by_role(self, role, name):
        return FakeLocator(self, f"{role}:{name}")

    def get_by_label(self, label):
        return FakeLocator(self, f"label:{label}")

    def goto(self, url, **_kw):
        if self.errors:
            raise PlaywrightError(self.errors.pop(0))
        self.actions.append(("goto", url))
        self.url = url
        return url

    def reload(self, **_kw):
        if self.errors:
            raise PlaywrightError(self.errors.pop(0))
        self.actions.append(("reload", self.url))

    def wait_for_url(self, target):
        self.waits.append(target)
        if self.landings:
            self.url = self.landings.pop(0)

    def wait_for_timeout(self, ms):
        self.actions.append(("pause", ms))

    def evaluate(self, script, arg=None):
        self.actions.append(("evaluate", script, arg))
        return self.evaluated.pop(0) if self.evaluated else None

    @contextmanager
    def expect_navigation(self):
        yield

    @contextmanager
    def expect_response(self, predicate):
        self.waits.append(predicate)
        yield


@pytest.fixture
def fake_page():
    return FakePage


class FakeCredentials:
    """Answers every secret key with "pw-<key>"."""

    @staticmethod
    def get(key):
        return f"pw-{key}"


@pytest.fixture
def page_env(monkeypatch, profile_factory):
    """An Environment stand-in for the page helpers: profile URLs per component, fake credentials, no cluster.

    deployment_for answers the component name; run_snippet of the modules in snippet_modules
    records (deployment, snippet, params) in env.snippets and answers env.snippet_result.
    """

    def build(*snippet_modules, ca_bundle=None):
        urls = {
            c: f"https://{c}.example.test"
            for c in ("openinwoner", "openarchiefbeheer", "openbeheer", "kiss", "ita", "pabc")
        }
        access = {"ca_bundle": ca_bundle} if ca_bundle else {}
        env = SimpleNamespace(
            profile=profile_factory(urls=urls, access=access),
            credentials=FakeCredentials(),
            kube=None,
            snippets=[],
            snippet_result=None,
            deployment_for=lambda component: component,
            session=requests.Session,
            ingress_ip=lambda: None,
        )

        def run_snippet(_kube, deployment, name, params):
            env.snippets.append((deployment, name, params))
            return env.snippet_result

        for module in snippet_modules:
            monkeypatch.setattr(module, "run_snippet", run_snippet)
        return env

    return build
