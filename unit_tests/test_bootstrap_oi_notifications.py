"""Unit tests for Open Inwoner's abonnement on kanaal zaken."""

import base64
import hashlib
import hmac
import json

import pytest

from podiumd_tests.bootstrap import oi_notifications
from podiumd_tests.bootstrap.oi_notifications import CLIENT_ID
from podiumd_tests.bootstrap.oi_notifications import STORE_KEY
from podiumd_tests.bootstrap.oi_notifications import WEBHOOK
from podiumd_tests.bootstrap.oi_notifications import OiNotifications
from podiumd_tests.bootstrap.oi_notifications import oi_notifications_missing
from podiumd_tests.bootstrap.runner import Context
from podiumd_tests.credential_store import CredentialStore
from podiumd_tests.credentials import env_var_name
from podiumd_tests.responses import UnexpectedStatusError

ON = "https://on.example.test"
OI = "https://oi.example.test"
ABONNEMENT = f"{ON}/api/v1/abonnement/a1"

pytestmark = pytest.mark.usefixtures("shells")


@pytest.fixture
def shells(monkeypatch):
    """The params of each oi_notifications snippet call; each answers present with a created config."""
    calls = []

    def run_snippet(_kube, _deployment, name, params):
        calls.append(params)
        assert name == "oi_notifications"
        return {"present": True, "record": {"config": 7}}

    monkeypatch.setattr(oi_notifications, "run_snippet", run_snippet)
    return calls


@pytest.fixture
def ctx(env_factory, profile_factory, fake_runner):
    def build(record=None, *, allowed=True):
        data = {STORE_KEY: base64.b64encode(json.dumps(record).encode()).decode()} if record else {}
        fake_runner.answers["get secret podiumd-tests-credentials"] = (0, json.dumps({"kind": "Secret", "data": data}))
        fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "openinwoner"}}]}))
        profile = profile_factory(
            urls={"opennotificaties": ON, "openinwoner": OI}, settings={"oi_notifications": str(allowed).lower()}
        )
        env = env_factory(profile, {env_var_name("ptest_bootstrap_nrc_secret"): "nrc"})
        return Context(env, CredentialStore(env.kube))

    return build


def test_not_allowed_is_present_and_applies_nothing(ctx, fake_http, shells):
    sent = fake_http()
    context = ctx(allowed=False)
    assert OiNotifications().is_present(context)
    assert OiNotifications().apply(context) == {}
    assert sent == []
    assert shells == []


@pytest.mark.parametrize(
    ("record", "status", "present"), [(None, 200, False), ({"abonnement": ABONNEMENT}, 404, False)]
)
def test_is_present_needs_the_recorded_abonnement(ctx, fake_http, record, status, present):
    fake_http({"GET /api/v1/abonnement/a1": (status, {})})
    assert OiNotifications().is_present(ctx(record)) is present


def test_apply_signs_the_abonnement_with_the_subscription_secret(ctx, fake_http, shells):
    sent = fake_http({"POST /api/v1/abonnement": (201, {"url": ABONNEMENT})})
    stored = OiNotifications().apply(ctx())
    subscription = shells[0]
    assert subscription["action"] == "apply"
    assert subscription["callback_url"] == f"{OI}/api/openzaak/notifications/webhook/zaken"
    body = json.loads(sent[0].body)
    header, payload, signature = body["auth"].removeprefix("Bearer ").split(".")
    expected = hmac.new(subscription["secret"].encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    assert base64.urlsafe_b64encode(expected).rstrip(b"=").decode() == signature
    assert json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["client_id"] == CLIENT_ID
    assert json.loads(stored[STORE_KEY]) == {"config": 7, "abonnement": ABONNEMENT}


def test_apply_removes_the_subscription_when_the_abonnement_fails(ctx, fake_http, shells):
    fake_http({"POST /api/v1/abonnement": (400, {})})
    with pytest.raises(UnexpectedStatusError):
        OiNotifications().apply(ctx())
    assert [(c["action"], c.get("record")) for c in shells] == [("apply", None), ("remove", {"config": 7})]


def test_remove_deletes_the_abonnement_before_the_subscription(ctx, fake_http, shells):
    sent = fake_http({"DELETE /api/v1/abonnement/a1": (204, None)})
    record = {"config": None, "abonnement": ABONNEMENT}
    assert OiNotifications().remove(ctx(record)) == (STORE_KEY,)
    assert [s.method for s in sent] == ["DELETE"]
    assert shells[0]["record"] == record


@pytest.mark.parametrize(
    ("callback", "kanaal", "missing"),
    [
        (f"https://portaal.example.test{WEBHOOK}", "zaken", False),
        (f"https://portaal.example.test{WEBHOOK}", "documenten", True),
        ("https://omc.example.test/Events/Listen", "zaken", True),
    ],
)
def test_oi_notifications_missing_needs_an_abonnement_calling_the_webhook(ctx, fake_http, callback, kanaal, missing):
    abonnement = {"callbackUrl": callback, "kanalen": [{"naam": kanaal}]}
    fake_http({"GET /api/v1/abonnement": (200, [abonnement])})
    assert (oi_notifications_missing(ctx().env) is not None) is missing
