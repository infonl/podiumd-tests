"""Unit tests for the Django admin login helpers."""

import pytest

from podiumd_tests.auth import django_admin


class FakeCredentials:
    def __init__(self, **values):
        self.values = values

    def optional(self, name):
        return self.values.get(name)


def test_superuser_login_skips_sso_only_apps_and_missing_accounts(env_factory, profile_factory):
    env = env_factory(
        profile_factory(urls={"openzaak": "https://x.test"}, settings={"django_admin_sso_only": "openzaak"})
    )
    with pytest.raises(pytest.skip.Exception, match="through Keycloak only"):
        django_admin.superuser_login(env, FakeCredentials(), "openzaak")  # pyright: ignore[reportArgumentType]
    env = env_factory(profile_factory(urls={"openzaak": "https://x.test"}))
    with pytest.raises(pytest.skip.Exception, match="no secrets"):
        django_admin.superuser_login(env, FakeCredentials(), "openzaak")  # pyright: ignore[reportArgumentType]


def test_superuser_login_logs_in_with_the_local_account(env_factory, profile_factory, monkeypatch):
    calls = []
    monkeypatch.setattr(
        django_admin, "admin_login", lambda http, url, user, password: calls.append((url, user, password))
    )
    env = env_factory(profile_factory(urls={"openzaak": "https://x.test"}))
    credentials = FakeCredentials(django_admin_username="admin", django_admin_password="pw")
    django_admin.superuser_login(env, credentials, "openzaak")  # pyright: ignore[reportArgumentType]
    assert calls == [("https://x.test", "admin", "pw")]
