"""Unit tests for OMC's chain helpers."""

import json

import requests

from podiumd_tests import omc
from podiumd_tests.clients.api import ApiClient
from podiumd_tests.mock_server import NAME
from podiumd_tests.mock_server import NOTIFY_EMAIL
from podiumd_tests.omc import EMAIL
from podiumd_tests.omc import make_inwoner_zaak
from podiumd_tests.omc import notify_request
from podiumd_tests.seed.openzaak import ZaaktypeParts
from podiumd_tests.seed.registry import ResourceRegistry


def test_notify_request_matches_the_address_and_the_template_of_the_setting(env_factory, fake_runner):
    wanted = {"path": NOTIFY_EMAIL, "body": {"email_address": "a@example.invalid", "template_id": "t-update"}}
    lines = [{"path": NOTIFY_EMAIL, "body": {"email_address": "a@example.invalid", "template_id": "t-create"}}, wanted]
    fake_runner.answers["printenv NOTIFY_TEMPLATEID_EMAIL_ZAAKUPDATE"] = (0, "t-update\n")
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "omc"}}]}))
    fake_runner.answers[f"exec deploy/{NAME}"] = (0, "".join(f"{json.dumps(line)}\n" for line in lines))
    found = notify_request(env_factory(), EMAIL, "a@example.invalid", "NOTIFY_TEMPLATEID_EMAIL_ZAAKUPDATE")
    assert found == wanted


def test_make_inwoner_zaak_gives_the_partij_and_the_initiator_one_bsn(monkeypatch):
    calls = []

    def recorder(name):
        return lambda *args, **kwargs: calls.append((name, args, kwargs)) or {}

    for name in ("make_partij", "make_partij_identificator", "make_digitaal_adres", "make_zaak", "make_rol"):
        monkeypatch.setattr(omc, name, recorder(name))
    parts = ZaaktypeParts("zt", [], {"initiator": "rt"}, "iot", {}, "", [])
    client = ApiClient(requests.Session(), "https://api.example.test", {})
    _, bsn = make_inwoner_zaak(client, client, ResourceRegistry("ptest-x"), parts, "a@example.invalid")
    called = {name: (args, kwargs) for name, args, kwargs in calls}
    assert called["make_partij_identificator"][0][3:] == ("bsn", bsn)
    assert called["make_digitaal_adres"][0][3] == "a@example.invalid"
    assert called["make_rol"][1] == {"inpBsn": bsn}
