"""Unit tests for the bootstrap step that switches on ZAC's ontvangstbevestiging."""

import base64
import json

import pytest
import requests

from podiumd_tests.bootstrap import Context
from podiumd_tests.bootstrap import zac as zac_step
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.zac import STORE_KEY
from podiumd_tests.bootstrap.zac import WANTED
from podiumd_tests.bootstrap.zac import ZacEmailConfirmation
from podiumd_tests.credential_store import CredentialStore
from podiumd_tests.credentials import env_var_name

ZAC = "https://zac.example.test"
UUID = "zt-uuid"
OFF = {"enabled": False, "id": 1}


@pytest.fixture
def ctx(env_factory, profile_factory, fake_runner, monkeypatch):
    def build(*, allowed=True, record=None):
        settings = {"productaanvraag_zaaktype": "zt-1", "zac_email_confirmation": allowed}
        environ = {env_var_name(ADMIN.store_key): "pw"}
        env = env_factory(profile_factory(urls={"zac": ZAC}, settings=settings), environ)
        secret = {"data": {STORE_KEY: _b64(json.dumps(record))}} if record is not None else {}
        fake_runner.answers["get secret podiumd-tests-credentials"] = (0, json.dumps({"kind": "Secret", **secret}))
        monkeypatch.setattr(zac_step, "zac_session", lambda *_: requests.Session())
        return Context(env, CredentialStore(env.kube))

    return build


def _b64(text):
    return base64.b64encode(text.encode()).decode()


def answers(confirmation):
    parameters = {"zaaktype": {"identificatie": "zt-1", "uuid": UUID}, "automaticEmailConfirmation": confirmation}
    return {
        "GET /rest/zaakafhandelparameters": (200, [parameters]),
        f"GET /rest/zaakafhandelparameters/{UUID}": (200, parameters),
        "PUT /rest/zaakafhandelparameters": (200, parameters),
    }


def test_without_the_profile_setting_nothing_changes(ctx, fake_http):
    sent = fake_http({})
    context = ctx(allowed=False)
    step = ZacEmailConfirmation(ADMIN)
    assert step.is_present(context)
    assert step.apply(context) == {}
    assert sent == []


def test_apply_switches_it_on_and_records_the_old_value(ctx, fake_http):
    sent = fake_http(answers(OFF))
    stored = ZacEmailConfirmation(ADMIN).apply(ctx())
    assert json.loads(stored[STORE_KEY]) == {UUID: OFF}
    put = next(s for s in sent if s.method == "PUT")
    assert json.loads(put.body)["automaticEmailConfirmation"] == {**WANTED, "id": 1}


def test_apply_leaves_a_confirmation_that_is_on(ctx, fake_http):
    sent = fake_http(answers({"enabled": True, "templateName": "Eigen", "emailSender": "x@gemeente.nl", "id": 1}))
    assert json.loads(ZacEmailConfirmation(ADMIN).apply(ctx())[STORE_KEY]) == {}
    assert not [s for s in sent if s.method == "PUT"]


def test_remove_puts_the_old_value_back(ctx, fake_http):
    sent = fake_http(answers({**WANTED, "id": 1}))
    assert ZacEmailConfirmation(ADMIN).remove(ctx(record={UUID: OFF})) == (STORE_KEY,)
    put = next(s for s in sent if s.method == "PUT")
    assert json.loads(put.body)["automaticEmailConfirmation"] == OFF


def test_remove_leaves_a_value_someone_else_changed(ctx, fake_http):
    sent = fake_http(answers({**WANTED, "templateName": "Eigen", "id": 1}))
    context = ctx(record={UUID: OFF})
    ZacEmailConfirmation(ADMIN).remove(context)
    assert not [s for s in sent if s.method == "PUT"]
    assert "changed by someone else" in context.notes[0]
