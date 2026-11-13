"""Unit tests for OMC's chain helpers."""

import json

import pytest
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


def omc_env(env_factory, fake_runner, setting, value):
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "omc"}}]}))
    fake_runner.answers[f"printenv {setting}"] = (0, f"{value}\n")
    return env_factory()


@pytest.mark.parametrize(
    ("value", "allowed"),
    [("a, ptest-zt ,b", True), ("*", True), ("niet-bestaande-id", False), ("", False)],
)
def test_is_listed_reads_a_comma_separated_setting_with_a_wildcard(env_factory, fake_runner, value, allowed):
    assert omc.is_listed(omc_env(env_factory, fake_runner, "IDS", value), "IDS", "ptest-zt") is allowed


def test_setting_skip_names_the_setting_and_its_value(env_factory, fake_runner):
    env = omc_env(env_factory, fake_runner, "IDS", "niet-bestaande-id")
    assert omc.setting_skip(env, "IDS", "ptest-zt", listed=False) is None
    assert omc.setting_skip(env, "IDS", "ptest-zt", listed=True) == (
        "OMC's IDS is 'niet-bestaande-id', which lacks ptest-zt"
    )


def test_expect_outcome_wants_the_status_and_the_reason(response_factory):
    answer = response_factory(status=206, json_body={"statusCode": 206, "statusDescription": "Dropped: why"})
    omc.expect_outcome(answer, 206, "Dropped")
    with pytest.raises(AssertionError, match="without 'other'"):
        omc.expect_outcome(answer, 206, "other")


def test_listen_posts_with_omcs_token(fake_http, env_factory, profile_factory, monkeypatch):
    monkeypatch.setattr(omc, "omc_token", lambda _env, issued: f"t{int(issued)}")
    sent = fake_http({"POST /Events/Listen": (202, {})})
    env = env_factory(profile=profile_factory(urls={"omc": "https://omc.example.test"}))
    omc.listen(requests.Session(), env, {"a": 1}, issued=5)
    assert (sent[0].url, sent[0].headers["Authorization"]) == ("https://omc.example.test/Events/Listen", "Bearer t5")


def test_zaak_notificatie_is_about_the_zaak_with_its_kenmerken():
    zaak = {"url": "z", "zaaktype": "zt", "bronorganisatie": "1", "vertrouwelijkheidaanduiding": "openbaar", "x": 2}
    found = omc.zaak_notificatie(zaak, "status", "s")
    assert (found["kanaal"], found["hoofdObject"], found["resourceUrl"]) == ("zaken", "z", "s")
    assert found["kenmerken"] == {"zaaktype": "zt", "bronorganisatie": "1", "vertrouwelijkheidaanduiding": "openbaar"}


def test_besluit_notificatie_is_about_the_besluit_and_its_document_link():
    besluit = {"url": "b", "besluittype": "bt", "verantwoordelijkeOrganisatie": "1"}
    found = omc.besluit_notificatie(besluit, {"url": "l"})
    assert (found["kanaal"], found["hoofdObject"], found["resourceUrl"]) == ("besluiten", "b", "l")
    assert found["kenmerken"] == {"besluittype": "bt", "verantwoordelijkeOrganisatie": "1"}


def test_bericht_event_is_a_cloudevent_about_the_bericht():
    event = omc.bericht_event("bericht-gepubliceerd", "b1")
    assert (event["type"], event["subject"]) == ("nl.overheid.berichten.bericht-gepubliceerd", "b1")
