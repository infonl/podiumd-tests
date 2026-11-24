"""Offline fakes for the unit tests: no cluster, no network."""

import io
import json
import subprocess

from collections import defaultdict
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import override

import pytest
import requests

from playwright.sync_api import Error as PlaywrightError
from requests.adapters import HTTPAdapter

from podiumd_tests import zac_api
from podiumd_tests.config import parse_profile
from podiumd_tests.environment import Environment


class FakeRunner:
    """Answers commands by the first matching argv fragment; records every call."""

    def __init__(self, answers=None):
        self.answers: dict[str, tuple[int, str]] = answers or {}
        self.calls: list[list[str]] = []
        self.stdins: list[str | None] = []

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
    response.raw = io.BytesIO(body if json_body is None else json.dumps(json_body).encode())
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
    answer 404. Bytes answer as the body itself. The real adapters (host-header mode) still run.
    """
    sent = []

    def install(answers=None):
        def fake_send(_adapter, request, **kwargs):
            sent.append(Sent(request.method, request.url, dict(request.headers), kwargs.get("timeout"), request.body))
            path = request.path_url.split("?")[0]
            table = answers or {}
            status, json_body = table.get(f"{request.method} {path}", table.get(path, (404, {"detail": "not found"})))
            if isinstance(json_body, bytes):
                response = response_factory(status=status, body=json_body, url=request.url)
            else:
                response = response_factory(status=status, json_body=json_body, url=request.url)
            response.request = request
            return response

        monkeypatch.setattr(HTTPAdapter, "send", fake_send)
        return sent

    return install


class FakeLocator:
    """A Playwright locator that records its actions on the FakePage; key names what it locates."""

    def __init__(self, page, key):
        self.page: FakePage = page
        self.key: str = key

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
        self.url: str = url
        self.errors: list[str] = list(errors)
        self.texts: dict[str, str] = texts or {}
        self._landings: list[str] = list(landings)
        self._evaluated: list[object] = list(evaluated)
        self.actions: list[tuple[object, ...]] = []
        self.waits: list[object] = []
        self.context: SimpleNamespace = SimpleNamespace(cookies=lambda: list(cookies))

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
        if self._landings:
            self.url = self._landings.pop(0)

    def wait_for_timeout(self, ms):
        self.actions.append(("pause", ms))

    def wait_for_load_state(self):
        self.actions.append(("load",))

    def title(self):
        return self.texts.get("title", "")

    def evaluate(self, script, arg=None):
        self.actions.append(("evaluate", script, arg))
        return self._evaluated.pop(0) if self._evaluated else None

    @contextmanager
    def expect_navigation(self):  # noqa: PLR6301  # fakes Page.expect_navigation
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

    def get(self, key):  # noqa: PLR6301  # fakes SecretResolver.get
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


class _KnownZac(defaultdict[str, bool]):
    """Every ZAC URL is known: False (ZAC 5.9) unless a test sets it."""

    @override
    def __contains__(self, key: object) -> bool:
        return True


@pytest.fixture(autouse=True)
def zac_5_9(monkeypatch):
    """ZAC fakes answer as ZAC 5.9: no process definitions, without asking; a test sets a URL to True for 5.12."""
    known = _KnownZac(bool)
    monkeypatch.setattr(zac_api, "_process_definitions", known)
    return known


# Keycloak's built-in direct grant flow: OTP in a conditional sub-flow, asked only of users that have one.
DIRECT_GRANT = [
    {
        "id": "u",
        "level": 0,
        "displayName": "Username Validation",
        "providerId": "direct-grant-validate-username",
        "requirement": "REQUIRED",
    },
    {"id": "s", "level": 0, "displayName": "Direct Grant - Conditional OTP", "requirement": "CONDITIONAL"},
    {
        "id": "c",
        "level": 1,
        "displayName": "Condition - user configured",
        "providerId": "conditional-user-configured",
        "requirement": "REQUIRED",
    },
    {"id": "o", "level": 1, "displayName": "OTP", "providerId": "direct-grant-validate-otp", "requirement": "REQUIRED"},
]


type Client = dict[str, object]
# A service-account user and the realm roles mapped to it.
type RoleMapping = tuple[str, list[str]]


class FakeMaster:
    """Keycloak admin calls on the master realm, kept in memory: clients, realm role mappings, requirements set."""

    flow: str = "direct grant"

    def __init__(self, executions=None):
        self.executions: list[dict[str, object]] = [dict(execution) for execution in executions or DIRECT_GRANT]
        self.set: list[tuple[str, str, str]] = []
        self.clients: dict[str, Client] = {}
        self.roles: list[RoleMapping] = []
        self.scopes: dict[str, str] = {}
        self.default_scopes: list[tuple[str, str]] = []

    def representation(self):
        return {"directGrantFlow": self.flow}

    def client_scopes(self):
        return self.scopes

    def add_default_scope(self, uuid, scope_id):
        self.default_scopes.append((uuid, scope_id))

    def flow_executions(self, flow):
        return [dict(execution) for execution in self.executions] if flow == self.flow else []

    def set_requirement(self, flow, execution, requirement):
        self.set.append((flow, execution["id"], requirement))
        next(found for found in self.executions if found["id"] == execution["id"])["requirement"] = requirement

    def client(self, client_id):
        return next((found for found in self.clients.values() if found["clientId"] == client_id), None)

    def create_client(self, body):
        uuid = f"uuid-{body['clientId']}"
        self.clients[uuid] = {**body, "id": uuid}
        return uuid

    def delete_client(self, uuid):
        self.clients.pop(uuid)

    def client_secret(self, uuid):
        return self.clients[uuid].get("secret", f"secret-{uuid}")

    def service_account_user_id(self, uuid):  # noqa: PLR6301  # fakes KeycloakAdmin.service_account_user_id
        return f"sa-{uuid}"

    def realm_roles(self, names):  # noqa: PLR6301  # fakes KeycloakAdmin.realm_roles
        return [{"name": name} for name in names]

    def add_realm_roles(self, user, roles):
        self.roles.append((user, [role["name"] for role in roles]))


@pytest.fixture
def fake_master():
    """A FakeMaster, by default with Keycloak's built-in direct grant flow."""
    return FakeMaster
