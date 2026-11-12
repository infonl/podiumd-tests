"""Unit tests for ZAC's signaleringen helpers."""

import json

import requests

from podiumd_tests import zac_signaleringen
from podiumd_tests.clients.api import ApiClient
from podiumd_tests.seed.registry import ResourceRegistry

ZAC = "https://zac.example.test"
SETTINGS = "/rest/signaleringen/instellingen"


def test_settings_are_read_and_saved(fake_http):
    setting = {"type": "ZAAK_OP_NAAM", "dashboard": True, "mail": False}
    sent = fake_http({f"GET {SETTINGS}": (200, [setting]), f"PUT {SETTINGS}": (200, {})})
    http = requests.Session()
    assert zac_signaleringen.signalering_settings(http, ZAC) == [setting]
    zac_signaleringen.save_signalering_setting(http, ZAC, setting)
    assert json.loads(sent[-1].body) == setting


def test_turn_signaleringen_saves_the_types_and_cleanup_restores_them(fake_http):
    before = [{"type": "TAAK_OP_NAAM", "dashboard": False, "mail": False}, {"type": "ZAAK_OP_NAAM", "dashboard": True}]
    sent = fake_http({f"GET {SETTINGS}": (200, before), f"PUT {SETTINGS}": (200, {})})
    registry = ResourceRegistry("run")
    zac_signaleringen.turn_signaleringen(requests.Session(), ZAC, registry, mail=True, TAAK_OP_NAAM=True)
    assert registry.cleanup() == []
    saved = [json.loads(request.body) for request in sent if request.method == "PUT"]
    assert saved == [{"type": "TAAK_OP_NAAM", "dashboard": True, "mail": True}, before[0]]


def test_group_signalering_mail_is_turned_on_and_off_at_cleanup(fake_http):
    url = "/rest/signaleringen/group/g1/instellingen"
    sent = fake_http({f"PUT {url}": (200, {})})
    registry = ResourceRegistry("run")
    zac_signaleringen.mail_group_signalering(requests.Session(), ZAC, registry, "g1", "ZAAK_OP_NAAM")
    assert registry.cleanup() == []
    assert [json.loads(request.body)["mail"] for request in sent] == [True, False]


def test_dashboard_lists_give_zaak_identificaties_and_taak_ids(fake_http):
    zaken = {"resultaten": [{"identificatie": "ZAAK-1"}], "totaal": 1}
    sent = fake_http(
        {
            "PUT /rest/signaleringen/zaken/ZAAK_OP_NAAM": (200, zaken),
            "GET /rest/signaleringen/taken/TAAK_OP_NAAM": (200, [{"id": "7", "naam": "Intake"}]),
        }
    )
    http = requests.Session()
    assert zac_signaleringen.signalering_zaken(http, ZAC, "ZAAK_OP_NAAM") == ["ZAAK-1"]
    assert json.loads(sent[0].body)["sortOrder"] == "DESC"
    assert zac_signaleringen.signalering_taken(http, ZAC) == ["7"]


def test_warning_list_gives_zaak_identificaties(fake_http):
    fake_http({"GET /rest/zaken/waarschuwing": (200, [{"identificatie": "ZAAK-2"}])})
    assert zac_signaleringen.zaak_waarschuwingen(requests.Session(), ZAC) == ["ZAAK-2"]


def test_dashboard_list_gives_the_zaken_as_zac_shows_them(fake_http):
    shown = {"identificatie": "ZAAK-1", "omschrijving": None}
    fake_http({"PUT /rest/signaleringen/zaken/ZAAK_OP_NAAM": (200, {"resultaten": [shown], "totaal": 1})})
    assert zac_signaleringen.signalering_overzichten(requests.Session(), ZAC, "ZAAK_OP_NAAM") == [shown]


def test_signalering_mail_searches_the_users_address_and_the_text(fake_http):
    sent = fake_http(
        {
            "GET /api/v1/search": (200, {"messages": [{"ID": "a"}]}),
            "GET /api/v1/message/a": (200, {"ID": "a", "HTML": "h"}),
        }
    )
    mailpit = ApiClient(requests.Session(), "https://mailpit.example.test/api/v1", {})
    mail = zac_signaleringen.signalering_mail(mailpit, ResourceRegistry("run"), "user", "ZAAK-1", timeout=0)
    assert mail == {"ID": "a", "HTML": "h"}
    assert "user%40example.invalid" in sent[0].url
    assert "ZAAK-1" in sent[0].url
