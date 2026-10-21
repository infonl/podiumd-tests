"""Unit tests for the navigation retry, the browser logins, the axe scan, Open Beheer's session and the Django admin login."""

from contextlib import nullcontext
from typing import Any

import pytest
import requests

from playwright.sync_api import Error as PlaywrightError

from podiumd_tests import accessibility
from podiumd_tests import browser
from podiumd_tests import openbeheer
from podiumd_tests.accessibility import describe_violation
from podiumd_tests.accessibility import wcag_violations
from podiumd_tests.auth.django_admin import AdminLoginError
from podiumd_tests.auth.django_admin import admin_login
from podiumd_tests.auth.django_admin import is_logged_in
from podiumd_tests.browser import NETWORK_CHANGED
from podiumd_tests.browser import browser_session
from podiumd_tests.browser import challenge_login
from podiumd_tests.browser import configure_totp
from podiumd_tests.browser import context_args
from podiumd_tests.browser import guard_navigation
from podiumd_tests.browser import headless_page
from podiumd_tests.browser import launch_args
from podiumd_tests.browser import redirect_login
from podiumd_tests.browser import refuse_cookies
from podiumd_tests.browser import retry_network_change
from podiumd_tests.browser import share_cookies

APP = "https://pabc.example.test"
COOKIE = {"name": "session", "value": "s1", "domain": "pabc.example.test"}


@pytest.fixture(autouse=True)
def no_login_lock(monkeypatch):
    monkeypatch.setattr(browser, "one_login_at_a_time", lambda _user: nullcontext())


def test_launch_args_map_every_profile_host_to_the_ingress_ip(page_env):
    env = page_env()
    assert launch_args(env) == []
    env.ingress_ip = lambda: "10.0.0.1"
    (rules,) = launch_args(env)
    assert rules.startswith("--host-resolver-rules=MAP ita.example.test 10.0.0.1,MAP kiss.example.test 10.0.0.1")


def test_context_args_skip_certificate_checks_only_for_a_local_ca(page_env):
    assert context_args(page_env()) == {}
    assert context_args(page_env(ca_bundle={"configmap": "ca", "key": "ca.pem"})) == {"ignore_https_errors": True}


def test_headless_page_guards_navigation_and_closes_the_browser(monkeypatch, page_env, fake_page):
    page = fake_page()
    calls: list[Any] = []

    class Chromium:
        def launch(self, args):
            calls.append(("launch", args))
            return self

        def new_context(self, **kwargs):
            calls.append(("context", kwargs))
            return type("C", (), {"new_page": lambda _s: page})()

        def close(self):
            calls.append("close")

    playwright = type("P", (), {"chromium": Chromium()})()
    monkeypatch.setattr(browser, "sync_playwright", lambda: nullcontext(playwright))
    with headless_page(page_env()) as opened:
        assert opened is page
        assert "goto" in vars(page)
    assert calls == [("launch", []), ("context", {}), "close"]


def test_redirect_login_logs_in_and_takes_the_browser_cookies(fake_page, page_env):
    page = fake_page(landings=[APP + "/"], cookies=[COOKIE])
    http = redirect_login(page, page_env(), APP, "kcc", "pw")
    assert page.actions == [
        ("goto", APP + "/"),
        ("fill", "#username", "kcc"),
        ("fill", "#password", "pw"),
        ("click", "#kc-login"),
    ]
    assert http.cookies.get("session") == "s1"
    assert page.waits[0](APP + "/zaken") and not page.waits[0]("https://keycloak.example.test/")


def test_challenge_login_waits_until_the_signin_callback_is_done(fake_page, page_env):
    page = fake_page()
    challenge_login(page, page_env(), APP, "kcc", "pw")
    assert page.actions[0] == ("goto", APP + "/api/challenge?returnUrl=%2F")
    assert not page.waits[0](APP + "/signin-oidc")
    assert page.waits[0](APP + "/")


def test_configure_totp_submits_the_code_of_the_offered_key(fake_page, monkeypatch):
    monkeypatch.setattr(browser, "totp", lambda secret: f"code-{secret}")
    page = fake_page(texts={"#kc-totp-secret-key": "ABCD EFGH"})
    configure_totp(page)
    assert page.actions == [
        ("click", "link:Unable to scan?"),
        ("fill", "#totp", "code-ABCD EFGH"),
        ("click", "#saveTOTPBtn"),
    ]


def test_browser_session_copies_cookies_without_domain(fake_page, page_env):
    http = browser_session(fake_page(cookies=[{"name": "a", "value": "1"}]), page_env())
    assert http.cookies.get("a") == "1"


def test_refuse_cookies_clicks_only_a_visible_banner(fake_page):
    hidden = fake_page()
    refuse_cookies(hidden)
    assert hidden.actions == []
    shown = fake_page(texts={"button:Alles weigeren": "Alles weigeren"})
    refuse_cookies(shown)
    assert shown.actions == [("click", "button:Alles weigeren")]


def test_wcag_violations_injects_axe_and_runs_the_aa_rules(monkeypatch, fake_page):
    monkeypatch.setattr(accessibility, "_axe_script", lambda: "/* axe */")
    violation = {"id": "color-contrast", "impact": "serious", "help": "Contrast", "nodes": [{}, {}]}
    page = fake_page(evaluated=[None, {"violations": [violation]}])
    assert wcag_violations(page) == [violation]
    assert page.actions[0] == ("evaluate", "/* axe */", None)
    assert page.actions[1][2]["runOnly"]["values"] == accessibility.WCAG_21_AA
    assert describe_violation(violation) == "color-contrast (serious, 2 elements): Contrast"


def test_openbeheer_session_logs_in_through_the_oidc_login(monkeypatch, page_env):
    logins = []
    monkeypatch.setattr(openbeheer, "form_login", lambda _http, url, user, pw: logins.append((url, user, pw)))
    assert isinstance(openbeheer.openbeheer_session(page_env(), "beheerder", "pw"), requests.Session)
    assert logins[0][0].startswith("https://openbeheer.example.test/")
    assert logins[0][1:] == ("beheerder", "pw")


LOGIN_FORM = (
    '<input name="csrfmiddlewaretoken" value="c1">'
    '<input name="admin_login_view-current_step" value="auth">'
    '<input name="next" value="/admin/">'
)


def test_admin_login_posts_the_wizard_step_with_csrf_and_next(fake_http, monkeypatch, response_factory):
    sent = fake_http()
    monkeypatch.setattr(
        requests.Session,
        "get",
        lambda _s, url, **_k: response_factory(body=LOGIN_FORM.encode(), url=url),
    )
    admin_login(requests.Session(), "https://oz.example.test", "admin", "pw")
    assert sent[0].url == "https://oz.example.test/admin/login/"
    body = str(sent[0].body)
    for field in ("csrfmiddlewaretoken=c1", "current_step=auth", "auth-username=admin", "next=%2Fadmin%2F"):
        assert field in body


def test_admin_login_refuses_a_form_without_wizard_step(monkeypatch, response_factory):
    monkeypatch.setattr(requests.Session, "get", lambda _s, url, **_k: response_factory(body=b"<form>", url=url))
    with pytest.raises(AdminLoginError, match="no CSRF token"):
        admin_login(requests.Session(), "https://oz.example.test", "admin", "pw")


def test_is_logged_in_wants_the_username_and_no_login_form(response_factory):
    assert is_logged_in(response_factory(body=b"Welkom, <strong>admin</strong>"), "admin")
    assert not is_logged_in(response_factory(body=b'<strong>admin</strong><input name="auth-username">'), "admin")
    assert not is_logged_in(response_factory(status=500, body=b"<strong>admin</strong>"), "admin")


def test_goto_and_reload_are_repeated_after_a_network_change_and_warn(fake_page):
    fake = fake_page(errors=[f"Page.goto: {NETWORK_CHANGED} at x"])
    page = guard_navigation(fake)
    with pytest.warns(UserWarning, match="goto .*retry 1 of 2"):
        assert page.goto("https://app.example.test/a") == "https://app.example.test/a"
    fake.errors.append(NETWORK_CHANGED)
    with pytest.warns(UserWarning, match="reload .*retry 1 of 2"):
        page.reload()
    assert [a[0] for a in fake.actions].count("pause") == 2
    assert fake.actions[-1] == ("reload", "https://app.example.test/a")


def test_other_errors_and_a_third_network_change_are_raised(fake_page):
    with pytest.raises(PlaywrightError, match="ERR_CONNECTION_REFUSED"):
        guard_navigation(fake_page(errors=["net::ERR_CONNECTION_REFUSED"])).goto("https://x.test/")
    fake = fake_page(errors=[NETWORK_CHANGED] * 3)
    with pytest.warns(UserWarning, match="retry 2 of 2"), pytest.raises(PlaywrightError):
        retry_network_change(fake, lambda: fake.goto("https://x.test/"), "goto")
    assert [a[0] for a in fake.actions].count("pause") == 2


def test_share_cookies_gives_the_browser_the_sessions_cookies():
    added = []
    page = type("P", (), {"context": type("C", (), {"add_cookies": staticmethod(added.extend)})()})()
    http = requests.Session()
    http.cookies.set("sessionid", "abc", domain="app.test", path="/")
    share_cookies(http, page)  # pyright: ignore[reportArgumentType]  # duck-typed page
    assert added == [{"name": "sessionid", "value": "abc", "domain": "app.test", "path": "/"}]
