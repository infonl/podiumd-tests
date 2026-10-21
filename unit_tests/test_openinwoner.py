"""Unit tests for the Open Inwoner page helpers, on a fake page."""

from contextlib import nullcontext

import pytest

from podiumd_tests import browser
from podiumd_tests import openinwoner
from podiumd_tests.auth.keycloak_admin import user_email
from podiumd_tests.openinwoner import LOGINS
from podiumd_tests.openinwoner import ask_anonymously
from podiumd_tests.openinwoner import begeleider_login
from podiumd_tests.openinwoner import count_accounts
from podiumd_tests.openinwoner import portal_login
from podiumd_tests.openinwoner import reset_begeleider
from podiumd_tests.openinwoner import search_data
from podiumd_tests.openinwoner import set_account
from podiumd_tests.openinwoner import set_site_configuration
from podiumd_tests.openinwoner import solve_captcha
from podiumd_tests.openinwoner import upload_document
from podiumd_tests.openinwoner import virus_scan_enabled

PORTAL = "https://openinwoner.example.test"
BANNER = "button:Alles weigeren"


@pytest.fixture(autouse=True)
def no_login_lock(monkeypatch):
    monkeypatch.setattr(browser, "one_login_at_a_time", lambda _user: nullcontext())


@pytest.fixture
def env(page_env):
    return page_env(openinwoner)


def test_portal_login_logs_in_and_closes_the_cookie_banner(fake_page, env):
    user, method = LOGINS["inwoner"]
    page = fake_page(landings=[PORTAL + "/"], texts={BANNER: "Alles weigeren"})
    portal_login(page, env, method, user, "/zaken")
    assert page.actions[0] == ("goto", PORTAL + "/digid-oidc/authenticate/?next=/zaken")
    assert ("fill", "#password", f"pw-{user.store_key}") in page.actions
    assert page.actions[-1] == ("click", BANNER)
    landed = page.waits[0]
    assert landed(PORTAL + "/zaken") and not landed(PORTAL + "/digid-oidc/callback/?code=1")


def test_a_first_eherkenning_login_completes_the_registration(fake_page, env):
    user, method = LOGINS["bedrijf"]
    page = fake_page(landings=[PORTAL + "/register/necessary/", PORTAL + "/"])
    portal_login(page, env, method, user, "/zaken")
    fill = next(a for a in page.actions if a[1] == 'input[name="email"]')
    assert fill[2] == user_email(user.username)
    assert ("click", "button:Voltooi registratie") in page.actions
    assert page.actions[-1] == ("goto", PORTAL + "/zaken")
    assert not page.waits[1](PORTAL + "/register/necessary/")


def test_ask_anonymously_fills_the_contact_form_and_solves_the_captcha(fake_page, env):
    page = fake_page(texts={".captcha__check": "Wat is 6 - 3?"})
    ask_anonymously(page, env, "Afval", "Wanneer?", "a@example.test")
    form = "#contactmoment-form"
    assert ("select", f'{form} select[name="subject"]', "Afval") in page.actions
    assert ("fill", f'{form} textarea[name="question"]', "Wanneer?") in page.actions
    assert ("fill", 'input[name="captcha"]', "3") in page.actions
    assert page.actions[-1] == ("click", f"{form} button:Verzenden")


def test_captcha_adds_and_refuses_a_question_without_sum(fake_page):
    page = fake_page(texts={".captcha__check": "Wat is 2 + 5?"})
    solve_captcha(page)
    assert page.actions == [("fill", 'input[name="captcha"]', "7")]
    with pytest.raises(AssertionError, match="no sum"):
        solve_captcha(fake_page(texts={".captcha__check": "Typ het woord"}))


def test_begeleider_login_posts_the_password_with_the_csrf_token(fake_page, env):
    page = fake_page(texts={'input[name="csrfmiddlewaretoken"]': "tok"})
    begeleider_login(page, env)
    _, _, (url, body) = next(a for a in page.actions if a[0] == "evaluate")
    assert url == PORTAL + "/accounts/login/"
    assert body["csrfmiddlewaretoken"] == "tok"
    assert body["password"].startswith("pw-")


def test_upload_document_waits_for_the_post_to_the_document_form(fake_page):
    page = fake_page()
    upload_document(page, "a.txt", b"x")
    assert page.actions == [
        ("files", '#document-upload input[name="file"]', [{"name": "a.txt", "mimeType": "text/plain", "buffer": b"x"}]),
        ("click", "#document-upload button:Upload documenten"),
    ]
    posted = type("R", (), {"url": PORTAL + "/document-form/", "request": type("Q", (), {"method": "POST"})})
    assert page.waits[0](posted)


def test_snippet_helpers_pass_their_parameters(env):
    env.snippet_result = {"old": 1}
    reset_begeleider(env)
    assert set_account(env, "999", phonenumber="06") == {"old": 1}
    assert set_site_configuration(env, name="x") == {"old": 1}
    assert search_data(env, "read", "ptest") == {"old": 1}
    assert virus_scan_enabled(env)
    assert [(d, n) for d, n, _ in env.snippets] == [
        ("openinwoner", "oi_begeleider_reset"),
        ("openinwoner", "oi_account"),
        ("openinwoner", "oi_site_configuration"),
        ("openinwoner", "oi_search_data"),
        ("openinwoner", "oi_virus_scan"),
    ]
    assert env.snippets[1][2] == {"bsn": "999", "fields": {"phonenumber": "06"}}
    assert env.snippets[3][2] == {"action": "read", "tag": "ptest", "products": []}


def test_count_accounts_asks_the_account_snippet_for_a_count(env):
    env.snippet_result = 1
    assert count_accounts(env, kvk="68750110") == 1
    assert env.snippets[-1][1:] == ("oi_account", {"count": {"kvk": "68750110"}})
