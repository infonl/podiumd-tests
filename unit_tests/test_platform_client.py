"""Unit tests for the platform ApiClients."""

import base64
import json

import pytest

from podiumd_tests.clients import platform
from podiumd_tests.credentials import env_var_name

URLS = {
    "openzaak": "https://oz.example.test",
    "opennotificaties": "https://on.example.test",
    "openklant": "https://ok.example.test",
    "objecten": "https://obj.example.test",
    "objecttypen": "https://ot.example.test",
    "mailpit": "https://mail.example.test",
}


def claims(client):
    payload = client.headers()["Authorization"].removeprefix("Bearer ").split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


@pytest.fixture
def env(env_factory, profile_factory):
    keys = ("zgw", "nrc", "openklant", "objecten", "objecttypen")
    environ = {env_var_name(f"ptest_bootstrap_{k}_{'secret' if k in {'zgw', 'nrc'} else 'token'}"): k for k in keys}
    return env_factory(profile_factory(urls=URLS), environ=environ)


def test_openzaak_client_signs_a_fresh_token_and_names_the_run_in_the_audittrail(env):
    client = platform.openzaak_client(env, "ptest-bootstrap-zgw", "ptest_bootstrap_zgw_secret", "ptest-1", lambda: "t1")
    assert claims(client)["client_id"] == "ptest-bootstrap-zgw"
    assert claims(client)["user_representation"] == "podiumd-tests ptest-1"
    assert client.headers()["X-Audit-Toelichting"] == "ptest-1 t1"
    assert client.base_url == URLS["openzaak"]


def test_opennotificaties_client_uses_the_nrc_client(env):
    client = platform.opennotificaties_client(env)
    assert claims(client)["client_id"] == "ptest-bootstrap-nrc"
    assert client.base_url == "https://on.example.test/api/v1"


@pytest.mark.parametrize(
    ("build", "root", "authorization"),
    [
        (platform.openklant_client, "https://ok.example.test/klantinteracties/api/v1", "Token openklant"),
        (platform.objecten_client, "https://obj.example.test/api/v2", "Token objecten"),
        (platform.objecttypen_client, "https://ot.example.test/api/v2", "Token objecttypen"),
        (platform.mailpit_client, "https://mail.example.test/api/v1", None),
    ],
)
def test_token_clients(env, build, root, authorization):
    client = build(env)
    assert client.base_url == root
    assert client.headers().get("Authorization") == authorization
