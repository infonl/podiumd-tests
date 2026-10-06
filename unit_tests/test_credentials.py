"""Unit tests for secret resolution and redaction."""

import base64
import json

import pytest

from podiumd_tests.credentials import Redactor
from podiumd_tests.credentials import SecretError
from podiumd_tests.credentials import env_var_name


def test_env_var_wins_over_the_profile(profile_factory, fake_runner, env_factory):
    profile = profile_factory(secrets={"ok2-token": {"k8s_secret": {"name": "s", "key": "k"}}})
    creds = env_factory(profile, {"PODIUMD_TESTS_SECRET_OK2_TOKEN": "from-env"}).credentials
    assert creds.get("ok2-token") == "from-env"
    assert fake_runner.calls == []


def test_k8s_secret_is_decoded(profile_factory, fake_runner, env_factory):
    encoded = base64.b64encode(b"s3cret-value").decode()
    fake_runner.answers["get secret kc -o json"] = (0, json.dumps({"data": {"password": encoded}}))
    profile = profile_factory(secrets={"pw": {"k8s_secret": {"name": "kc", "key": "password"}}})
    assert env_factory(profile).credentials.get("pw") == "s3cret-value"


def test_keyvault_uses_the_profile_vault(profile_factory, fake_runner, env_factory):
    fake_runner.answers["az keyvault secret show --vault-name my-kv --name user-pw"] = (0, "kv-value\n")
    profile = profile_factory(keyvault="my-kv", secrets={"pw": {"keyvault": {"secret": "user-pw"}}})
    assert env_factory(profile).credentials.get("pw") == "kv-value"


def test_zgw_jwt_secret_runs_a_django_snippet(profile_factory, fake_runner, env_factory):
    fake_runner.answers["exec deploy/openzaak -- python /app/src/manage.py shell -c"] = (
        0,
        "118 objects imported automatically (use -v 2 for details).\n\nPTEST_VALUE=jwt-secret\n",
    )
    profile = profile_factory(secrets={"oz": {"zgw_jwt_secret": {"deployment": "openzaak", "client_id": "zac"}}})
    assert env_factory(profile).credentials.get("oz") == "jwt-secret"
    assert "identifier='zac'" in fake_runner.calls[0][-1]


def test_failures_name_the_secret_and_source(profile_factory, env_factory):
    profile = profile_factory(secrets={"pw": {"pod_env": {"deployment": "pabc", "var": "API_KEY__0"}}})
    with pytest.raises(SecretError, match=r"secret 'pw' \(pod_env\)"):
        env_factory(profile).credentials.get("pw")


def test_unknown_secret_mentions_the_env_var(env_factory):
    with pytest.raises(SecretError, match="PODIUMD_TESTS_SECRET_MISSING"):
        env_factory().credentials.get("missing")


def test_resolved_values_are_redacted(env_factory):
    env = env_factory(environ={env_var_name("token"): "abcd-1234"})
    env.credentials.get("token")
    assert env.redactor.redact("Bearer abcd-1234 sent") == "Bearer *** sent"


def test_dev_defaults_are_not_redacted_but_overrides_are(profile_factory, env_factory):
    profile = profile_factory(
        estate="minikube", secrets={"user": {"dev_default": "admin"}, "pw": {"dev_default": "admin"}}
    )
    env = env_factory(profile, {env_var_name("pw"): "s3cret-override"})
    assert env.credentials.get("user") == "admin"
    assert env.credentials.get("pw") == "s3cret-override"
    assert env.redactor.redact("keycloak-admin s3cret-override") == "keycloak-admin ***"


def test_redactor_ignores_very_short_values():
    redactor = Redactor()
    redactor.add("ab")
    assert redactor.redact("abc") == "abc"


def test_keyvault_without_az_names_the_secret(profile_factory, env_factory):
    def runner(args, _timeout):
        raise FileNotFoundError(args[0])

    profile = profile_factory(keyvault="my-kv", secrets={"pw": {"keyvault": {"secret": "user-pw"}}})
    with pytest.raises(SecretError, match=r"secret 'pw' \(keyvault\): az keyvault .*: az not found on PATH"):
        env_factory(profile, runner=runner).credentials.get("pw")


def test_optional_secrets_come_from_profile_or_env_var(profile_factory, env_factory):
    environ = {env_var_name("grafana_password"): "from-env"}
    profile = profile_factory(secrets={"grafana_username": {"k8s_secret": {"name": "s", "key": "k"}}})
    creds = env_factory(profile, environ).credentials
    assert creds.configured("grafana_username")
    assert creds.configured("grafana_password")
    assert creds.optional("grafana_password") == "from-env"
    assert not creds.configured("zgw_client_secret")
    assert creds.optional("zgw_client_secret") is None
