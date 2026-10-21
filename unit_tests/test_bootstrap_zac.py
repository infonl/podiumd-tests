"""Unit tests for the bootstrap steps that switch on parts of ZAC's zaakafhandelparameters."""

import base64
import json

import pytest
import requests

from podiumd_tests.bootstrap import Context
from podiumd_tests.bootstrap import zac as zac_step
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.zac import AANVULLENDE_INFORMATIE
from podiumd_tests.bootstrap.zac import EMAIL_CONFIRMATION
from podiumd_tests.bootstrap.zac import ZacParameters
from podiumd_tests.credential_store import CredentialStore
from podiumd_tests.credentials import env_var_name
from podiumd_tests.json_data import entries

ZAC = "https://zac.example.test"
UUID = "zt-uuid"
OFF = {"enabled": False, "id": 1}
WANTED = EMAIL_CONFIRMATION.wanted
STEP = ZacParameters(ADMIN, "zac-email-confirmation", "zac_email_confirmation", EMAIL_CONFIRMATION)
STORE_KEY = STEP.store_key


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
    parameters = {
        "id": 2,
        "zaaktype": {"identificatie": "zt-1", "uuid": UUID},
        "automaticEmailConfirmation": confirmation,
    }
    return {
        "GET /rest/zaakafhandelparameters": (200, [parameters]),
        f"GET /rest/zaakafhandelparameters/{UUID}": (200, parameters),
        "PUT /rest/zaakafhandelparameters": (200, parameters),
    }


def test_without_the_profile_setting_nothing_changes(ctx, fake_http):
    sent = fake_http({})
    context = ctx(allowed=False)
    assert STEP.is_present(context)
    assert STEP.apply(context) == {}
    assert sent == []


def test_apply_switches_it_on_and_records_the_old_value(ctx, fake_http):
    sent = fake_http(answers(OFF))
    stored = STEP.apply(ctx())
    assert json.loads(stored[STORE_KEY]) == {UUID: OFF}
    put = next(s for s in sent if s.method == "PUT")
    assert json.loads(put.body)["automaticEmailConfirmation"] == {**OFF, **WANTED}


def test_apply_leaves_a_confirmation_that_is_on(ctx, fake_http):
    sent = fake_http(answers({"enabled": True, "templateName": "Eigen", "emailSender": "x@gemeente.nl", "id": 1}))
    assert json.loads(STEP.apply(ctx())[STORE_KEY]) == {}
    assert not [s for s in sent if s.method == "PUT"]


def test_apply_fails_without_zaakafhandelparameters(ctx, fake_http):
    fake_http({"GET /rest/zaakafhandelparameters": (200, [{"id": None, "zaaktype": {"identificatie": "zt-1"}}])})
    with pytest.raises(LookupError, match="no zaakafhandelparameters for zaaktype zt-1"):
        STEP.apply(ctx())


def test_remove_puts_the_old_value_back(ctx, fake_http):
    sent = fake_http(answers({**WANTED, "id": 1}))
    assert STEP.remove(ctx(record={UUID: OFF})) == (STORE_KEY,)
    put = next(s for s in sent if s.method == "PUT")
    assert json.loads(put.body)["automaticEmailConfirmation"] == OFF


def test_remove_leaves_a_value_someone_else_changed(ctx, fake_http):
    sent = fake_http(answers({**WANTED, "templateName": "Eigen", "id": 1}))
    context = ctx(record={UUID: OFF})
    STEP.remove(context)
    assert not [s for s in sent if s.method == "PUT"]
    assert "changed by someone else" in context.notes[0]


def test_store_key_keeps_the_name_of_the_email_confirmation_record():
    assert STORE_KEY == "ptest_bootstrap_zac_email_confirmation_record"


def test_human_task_part_switches_on_only_its_plan_item():
    items = [
        {"id": 1, "actief": False, "planItemDefinition": {"id": "GOEDKEUREN"}},
        {"id": 2, "actief": False, "planItemDefinition": {"id": "AANVULLENDE_INFORMATIE"}},
    ]
    parameters = {"humanTaskParameters": items}
    old = AANVULLENDE_INFORMATIE.read(parameters)
    assert old == items[1]
    assert not AANVULLENDE_INFORMATIE.is_on(old)
    changed = AANVULLENDE_INFORMATIE.write(parameters, {**old, **AANVULLENDE_INFORMATIE.wanted})
    assert [i["actief"] for i in entries(changed["humanTaskParameters"])] == [False, True]
    assert AANVULLENDE_INFORMATIE.is_mine(AANVULLENDE_INFORMATIE.read(changed))
