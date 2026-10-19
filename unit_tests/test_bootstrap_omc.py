"""Unit tests for OMC's abonnement on kanaal zaken."""

import base64
import json
import time

import pytest

from podiumd_tests.bootstrap import Context
from podiumd_tests.bootstrap.omc import STORE_KEY
from podiumd_tests.bootstrap.omc import VALIDITY
from podiumd_tests.bootstrap.omc import OmcAbonnement
from podiumd_tests.credential_store import CredentialStore
from podiumd_tests.credentials import env_var_name

ON = "https://on.example.test"
ABONNEMENT = f"{ON}/api/v1/abonnement/a1"


def b64url_json(part):
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


@pytest.fixture
def ctx(env_factory, profile_factory, fake_runner):
    def build(record=None):
        data = {STORE_KEY: base64.b64encode(json.dumps(record).encode()).decode()} if record else {}
        fake_runner.answers["get secret podiumd-tests-credentials"] = (0, json.dumps({"kind": "Secret", "data": data}))
        fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "omc"}}]}))
        for var in ("ISSUER", "AUDIENCE", "USERID", "USERNAME"):
            fake_runner.answers[f"printenv OMC_AUTH_JWT_{var}"] = (0, f"{var.lower()}\n")
        environ = {env_var_name("ptest_bootstrap_nrc_secret"): "nrc", env_var_name("omc_jwt_secret"): "omc"}
        env = env_factory(profile_factory(urls={"opennotificaties": ON, "omc": "https://omc.example.test"}), environ)
        return Context(env, CredentialStore(env.kube))

    return build


@pytest.mark.parametrize(
    ("record", "status", "present"),
    [
        (None, 200, False),
        ({"url": ABONNEMENT, "expires": time.time() + 60}, 200, False),
        ({"url": ABONNEMENT, "expires": time.time() + VALIDITY}, 200, True),
        ({"url": ABONNEMENT, "expires": time.time() + VALIDITY}, 404, False),
    ],
    ids=["unrecorded", "about-to-expire", "valid", "deleted"],
)
def test_is_present(ctx, fake_http, record, status, present):
    fake_http({"GET /api/v1/abonnement/a1": (status, {})})
    assert OmcAbonnement().is_present(ctx(record)) is present


def test_apply_replaces_the_recorded_abonnement_with_a_fresh_token(ctx, fake_http):
    sent = fake_http(
        {
            "DELETE /api/v1/abonnement/old": (204, None),
            "POST /api/v1/abonnement": (201, {"url": ABONNEMENT}),
        }
    )
    stored = OmcAbonnement().apply(ctx({"url": f"{ON}/api/v1/abonnement/old", "expires": 0}))
    assert [s.method for s in sent] == ["DELETE", "POST"]
    body = json.loads(sent[1].body)
    assert body["callbackUrl"] == "https://omc.example.test/Events/Listen"
    claims = b64url_json(body["auth"].removeprefix("Bearer ").split(".")[1])
    assert (claims["iss"], claims["aud"], claims["exp"] - claims["iat"]) == ("issuer", "audience", VALIDITY)
    assert json.loads(stored[STORE_KEY])["url"] == ABONNEMENT


def test_remove_without_record_only_drops_the_key(ctx, fake_http):
    sent = fake_http()
    assert OmcAbonnement().remove(ctx()) == (STORE_KEY,)
    assert sent == []
