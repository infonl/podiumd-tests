"""Unit tests for the Django admin login helpers."""

from types import SimpleNamespace

import pytest

from podiumd_tests.auth import django_admin
from podiumd_tests.bootstrap.steps import DJANGO_ADMINS


def test_superuser_login_skips_sso_only_apps(env_factory, profile_factory):
    env = env_factory(
        profile_factory(urls={"openzaak": "https://x.test"}, settings={"django_admin_sso_only": "openzaak"})
    )
    with pytest.raises(pytest.skip.Exception, match="through Keycloak only"):
        django_admin.superuser_login(env, lambda *_names: None, "openzaak")


@pytest.mark.parametrize(
    ("component", "login"),
    [
        ("openzaak", "ptest-bootstrap-openzaak-admin"),
        ("openinwoner", "ptest-bootstrap-openinwoner-admin@example.invalid"),
    ],
)
def test_superuser_login_logs_in_as_the_test_superuser(env_factory, profile_factory, monkeypatch, component, login):
    calls, needed = [], []
    monkeypatch.setattr(
        django_admin, "admin_login", lambda _http, url, user, password: calls.append((url, user, password))
    )
    env = env_factory(profile_factory(urls={component: "https://x.test"}))
    monkeypatch.setattr(env.credentials, "get", lambda name: f"pw-{name}")
    assert django_admin.superuser_login(env, lambda *names: needed.extend(names), component)[2] == login
    step = DJANGO_ADMINS[component]
    assert needed == [step.name]
    assert calls == [("https://x.test", login, f"pw-{step.store_key}")]


def test_the_admin_step_also_removes_the_user_an_oidc_login_of_the_test_admin_made():
    sso_user = {"username": "ptest-bootstrap-admin", "email": "ptest-bootstrap-admin@example.invalid"}
    assert all(step.params["sso_users"] == [sso_user] for step in DJANGO_ADMINS.values())


def test_totp_follows_rfc_6238():
    # RFC 6238 appendix B, SHA-1 at T=59: 94287082, of which django_otp uses the last 6 digits.
    assert django_admin.totp(b"12345678901234567890".hex(), 59) == "287082"


def test_the_token_step_gets_the_totp_of_the_password(response_factory, monkeypatch):
    form = '<input name="csrfmiddlewaretoken" value="c"><input name="admin_login_view-current_step" value="{}">'
    pages = iter([form.format("token").encode(), b"<strong>admin</strong>"])
    posted = []

    session = SimpleNamespace(
        get=lambda url: response_factory(body=form.format("auth").encode(), url=url),
        post=lambda url, data, **_: posted.append(data) or response_factory(body=next(pages), url=url),
    )

    monkeypatch.setattr(django_admin, "totp", lambda key: f"code-{key}")
    django_admin.admin_login(session, "https://x.test", "admin", "pw")  # pyright: ignore[reportArgumentType]
    assert [data["admin_login_view-current_step"] for data in posted] == ["auth", "token"]
    assert posted[1]["token-otp_token"] == f"code-{django_admin.password_totp_key('pw')}"
