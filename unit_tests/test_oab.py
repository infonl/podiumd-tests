"""Unit tests for the Open Archiefbeheer helpers."""

import json

from types import SimpleNamespace

import pytest
import requests

from podiumd_tests import oab
from podiumd_tests import workloads
from podiumd_tests.bootstrap.names import PREFIX
from podiumd_tests.bootstrap.steps import django_secret_key

OAB = "https://openarchiefbeheer.example.test"


def test_ui_login_fills_the_form_once_the_spa_enabled_it(monkeypatch, fake_page, page_env):
    enabled = []
    monkeypatch.setattr(
        oab, "expect", lambda locator: type("E", (), {"to_be_enabled": lambda _s: enabled.append(locator.key)})()
    )
    page = fake_page(cookies=[{"name": "csrftoken"}])
    oab.ui_login(page, page_env(), "record-manager")
    assert enabled == ["button:Inloggen"]
    assert page.actions == [
        ("goto", f"{OAB}/login"),
        ("fill", "label:Gebruikersnaam", f"{PREFIX}-record-manager"),
        ("fill", "label:Wachtwoord", f"pw-{django_secret_key('openarchiefbeheer', 'record-manager')}"),
        ("click", "button:Inloggen"),
    ]
    assert page.waits == ["**/destruction-lists"]


def test_login_echoes_the_csrf_token_and_takes_the_rotated_one(fake_http, page_env, monkeypatch):
    sent = fake_http({"/api/v1/whoami/": (200, {}), "POST /api/v1/auth/login/": (204, None)})
    tokens = iter(["first", "rotated"])
    monkeypatch.setattr("requests.cookies.RequestsCookieJar.get", lambda *_a, **_k: next(tokens))
    http = oab.login(page_env(), "beoordelaar")
    assert sent[1].headers["X-CSRFToken"] == "first"
    assert json.loads(sent[1].body)["username"] == f"{PREFIX}-beoordelaar"
    assert http.headers["X-CSRFToken"] == "rotated"


def test_snippet_helpers_pass_their_parameters(page_env):
    env = page_env(oab)
    env.snippet_result = {"old": True}
    oab.cache_zaken(env, ["z1"], cached=True)
    oab.cache_zaken(env, ["z1"], cached=False)
    assert oab.set_config(env, "EmailConfig", {"x": 1}) == {"old": True}
    oab.destroy_now(env, "u-1")
    assert [(n, p) for _, n, p in env.snippets] == [
        ("oab_zaken", {"action": "cache", "urls": ["z1"]}),
        ("oab_zaken", {"action": "uncache", "urls": ["z1"]}),
        ("oab_config", {"model": "EmailConfig", "fields": {"x": 1}}),
        ("oab_destroy_now", {"uuid": "u-1"}),
    ]


@pytest.mark.parametrize(("version", "xfail"), [((2, 0, 0), False), ((2, 1, 2), True), (None, False)])
def test_admin_logout_bug_is_expected_from_2_1(monkeypatch, version, xfail):
    monkeypatch.setattr(
        workloads, "component_versions", lambda _env, _c: {} if version is None else {"openarchiefbeheer": version}
    )
    markers = []
    oab.expect_admin_logout_bug(SimpleNamespace(applymarker=markers.append), None)  # pyright: ignore[reportArgumentType]
    assert bool(markers) is xfail


API = f"{OAB}/api/v1"
USERS = [{"pk": 7, "username": f"{PREFIX}-reviewer"}, {"pk": 9, "username": f"{PREFIX}-archivist"}]


def _bodies(sent, suffix):
    return [json.loads(request.body) for request in sent if request.url.endswith(suffix) and request.body]


def test_list_goes_from_new_to_destroyed(fake_http, page_env):
    sent = fake_http(
        {
            "/api/v1/users/": (200, USERS),
            "POST /api/v1/destruction-lists/": (201, {"uuid": "l-1"}),
            "/api/v1/destruction-lists/l-1/mark_ready_review/": (201, {}),
            "/api/v1/destruction-list-reviews/": (201, {"pk": 3}),
            "/api/v1/destruction-lists/l-1/make_final/": (201, {}),
            "/api/v1/destruction-lists/l-1/queue_destruction/": (200, {}),
            "GET /api/v1/destruction-lists/l-1/": (200, {"processingStatus": "failed", "status": "ready_to_delete"}),
        }
    )
    env = page_env(oab)
    http = requests.Session()
    registry = SimpleNamespace(tagged=lambda name: f"run-{name}")
    lijst = oab.ready_to_delete(lambda _role: http, API, {"url": "z-1"}, registry)  # pyright: ignore[reportArgumentType]
    assert oab.run_destruction(env, lambda _role: http, API, lijst) == "failed"
    assert oab.list_status(lambda _role: http, API, lijst) == "ready_to_delete"
    created = _bodies(sent, "/destruction-lists/")[0]
    assert (created["add"], created["reviewer"], created["name"].startswith("run-vernietigingslijst-")) == (
        [{"zaak": "z-1"}],
        {"user": 7},
        True,
    )
    decisions = [body["decision"] for body in _bodies(sent, "/destruction-list-reviews/")]
    assert (_bodies(sent, "/make_final/")[0]["user"], decisions) == (9, ["accepted", "accepted"])
    assert env.snippets == [("openarchiefbeheer", "oab_destroy_now", {"uuid": "l-1"})]


def test_new_list_stays_new_unless_ready(fake_http):
    sent = fake_http({"/api/v1/users/": (200, USERS), "POST /api/v1/destruction-lists/": (201, {"uuid": "l-2"})})
    http = requests.Session()
    registry = SimpleNamespace(tagged=lambda name: name)
    zaken = [{"url": "z-1"}, {"url": "z-2"}]
    assert oab.new_list(lambda _role: http, API, zaken, registry, ready=False) == "l-2"  # pyright: ignore[reportArgumentType]
    assert all(not request.url.endswith("/mark_ready_review/") for request in sent)
    assert oab.user_pk(lambda _role: http, API, "archivist") == 9
