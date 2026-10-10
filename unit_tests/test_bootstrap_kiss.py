"""Unit tests for the bootstrap step that adds KISS's kanalen."""

import base64
import json

import pytest

from podiumd_tests.bootstrap import Context
from podiumd_tests.bootstrap import kiss as kiss_step
from podiumd_tests.bootstrap.kiss import STORE_KEY
from podiumd_tests.bootstrap.kiss import KissKanalen
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.credential_store import CredentialStore
from podiumd_tests.credentials import env_var_name

KISS = "https://kiss.example.test"


@pytest.fixture
def ctx(env_factory, profile_factory, fake_runner, monkeypatch):
    def build(*, allowed=True, record=None):
        settings = {"kiss_kanalen": allowed}
        env = env_factory(
            profile_factory(urls={"kiss": KISS}, settings=settings), {env_var_name(ADMIN.store_key): "pw"}
        )
        data = {"data": {STORE_KEY: base64.b64encode(json.dumps(record).encode()).decode()}} if record else {}
        fake_runner.answers["get secret podiumd-tests-credentials"] = (0, json.dumps({"kind": "Secret", **data}))
        monkeypatch.setattr(kiss_step, "form_login", lambda *_: None)
        return Context(env, CredentialStore(env.kube))

    return build


def test_without_the_profile_setting_nothing_changes(ctx, fake_http):
    sent = fake_http({})
    context = ctx(allowed=False)
    assert KissKanalen(ADMIN).is_present(context)
    assert KissKanalen(ADMIN).apply(context) == {}
    assert sent == []


def test_apply_adds_only_the_missing_kanalen(ctx, fake_http):
    sent = fake_http(
        {
            "GET /api/KanalenBeheerOverzicht": (200, [{"id": "1", "naam": "Telefoon"}]),
            "POST /api/KanaalToevoegen/": (204, None),
        }
    )
    stored = KissKanalen(ADMIN).apply(ctx())
    assert json.loads(stored[STORE_KEY]) == ["Balie", "Internet"]
    assert sorted(json.loads(s.body)["naam"] for s in sent if s.method == "POST") == ["Balie", "Internet"]


def test_remove_deletes_only_what_apply_added(ctx, fake_http):
    sent = fake_http(
        {
            "GET /api/KanalenBeheerOverzicht": (200, [{"id": "1", "naam": "Telefoon"}, {"id": "2", "naam": "Balie"}]),
            "DELETE /api/KanaalVerwijderen/2": (204, None),
        }
    )
    assert KissKanalen(ADMIN).remove(ctx(record=["Balie"])) == (STORE_KEY,)
    assert [s.url.removeprefix(KISS) for s in sent if s.method == "DELETE"] == ["/api/KanaalVerwijderen/2"]
