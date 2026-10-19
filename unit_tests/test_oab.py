"""Unit tests for the Open Archiefbeheer helpers."""

import json

from podiumd_tests import oab
from podiumd_tests.bootstrap.names import PREFIX
from podiumd_tests.bootstrap.steps import django_secret_key

OAB = "https://openarchiefbeheer.example.test"


def test_ui_login_fills_the_form_once_the_spa_enabled_it(monkeypatch, fake_page, page_env):
    enabled = []
    monkeypatch.setattr(
        oab, "expect", lambda locator: type("E", (), {"to_be_enabled": lambda _s: enabled.append(locator.key)})()
    )
    page = fake_page()
    oab.ui_login(page, page_env(), "record-manager")
    assert enabled == ["button:Inloggen"]
    assert page.actions == [
        ("goto", OAB + "/login"),
        ("fill", "label:Gebruikersnaam", f"{PREFIX}-record-manager"),
        ("fill", "label:Wachtwoord", "pw-" + django_secret_key("openarchiefbeheer", "record-manager")),
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
    assert oab.set_archive_config(env, {"x": 1}) == {"old": True}
    oab.destroy_now(env, "u-1")
    assert [(n, p) for _, n, p in env.snippets] == [
        ("oab_zaken", {"action": "cache", "urls": ["z1"]}),
        ("oab_zaken", {"action": "uncache", "urls": ["z1"]}),
        ("oab_archive_config", {"fields": {"x": 1}}),
        ("oab_destroy_now", {"uuid": "u-1"}),
    ]
