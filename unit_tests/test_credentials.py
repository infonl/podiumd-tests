"""Unit tests for secret resolution and redaction."""

import base64
import json

import pytest

from podiumd_tests.credentials import Redactor
from podiumd_tests.credentials import SecretError
from podiumd_tests.credentials import SecretResolver
from podiumd_tests.credentials import env_var_name
from podiumd_tests.kube import Kube


def resolver(profile, runner, environ=None):
    return SecretResolver(profile, Kube("ctx", "podiumd", runner), Redactor(), runner, environ or {})


def test_env_var_wins_over_the_profile(profile_factory, fake_runner):
    profile = profile_factory(secrets={"ok2-token": {"k8s_secret": {"name": "s", "key": "k"}}})
    creds = resolver(profile, fake_runner, {"PODIUMD_TESTS_SECRET_OK2_TOKEN": "from-env"})
    assert creds.get("ok2-token") == "from-env"
    assert fake_runner.calls == []


def test_k8s_secret_is_decoded(profile_factory, fake_runner):
    encoded = base64.b64encode(b"s3cret-value").decode()
    fake_runner.answers["get secret kc -o json"] = (0, json.dumps({"data": {"password": encoded}}))
    profile = profile_factory(secrets={"pw": {"k8s_secret": {"name": "kc", "key": "password"}}})
    assert resolver(profile, fake_runner).get("pw") == "s3cret-value"


def test_keyvault_uses_the_profile_vault(profile_factory, fake_runner):
    fake_runner.answers["az keyvault secret show --vault-name my-kv --name user-pw"] = (0, "kv-value\n")
    profile = profile_factory(keyvault="my-kv", secrets={"pw": {"keyvault": {"secret": "user-pw"}}})
    assert resolver(profile, fake_runner).get("pw") == "kv-value"


def test_zgw_jwt_secret_runs_a_django_snippet(profile_factory, fake_runner):
    fake_runner.answers["exec deploy/openzaak -- python manage.py shell -c"] = (0, "jwt-secret\n")
    profile = profile_factory(secrets={"oz": {"zgw_jwt_secret": {"deployment": "openzaak", "client_id": "zac"}}})
    assert resolver(profile, fake_runner).get("oz") == "jwt-secret"
    assert "identifier='zac'" in fake_runner.calls[0][-1]


def test_failures_name_the_secret_and_source(profile_factory, fake_runner):
    profile = profile_factory(secrets={"pw": {"pod_env": {"deployment": "pabc", "var": "API_KEY__0"}}})
    with pytest.raises(SecretError, match=r"secret 'pw' \(pod_env\)"):
        resolver(profile, fake_runner).get("pw")


def test_unknown_secret_mentions_the_env_var(profile_factory, fake_runner):
    with pytest.raises(SecretError, match="PODIUMD_TESTS_SECRET_MISSING"):
        resolver(profile_factory(), fake_runner).get("missing")


def test_resolved_values_are_redacted(profile_factory, fake_runner):
    redactor = Redactor()
    environ = {env_var_name("token"): "abcd-1234"}
    creds = SecretResolver(profile_factory(), Kube("ctx", "podiumd", fake_runner), redactor, fake_runner, environ)
    creds.get("token")
    assert redactor.redact("Bearer abcd-1234 sent") == "Bearer *** sent"


def test_redactor_ignores_very_short_values():
    redactor = Redactor()
    redactor.add("ab")
    assert redactor.redact("abc") == "abc"
