"""Unit tests for ZAC's signaleringen helpers."""

import json

import requests

from podiumd_tests import zac_signaleringen

ZAC = "https://zac.example.test"
SETTINGS = "/rest/signaleringen/instellingen"


def test_settings_are_read_and_saved(fake_http):
    setting = {"type": "ZAAK_OP_NAAM", "dashboard": True, "mail": False}
    sent = fake_http({f"GET {SETTINGS}": (200, [setting]), f"PUT {SETTINGS}": (200, {})})
    http = requests.Session()
    assert zac_signaleringen.signalering_settings(http, ZAC) == [setting]
    zac_signaleringen.save_signalering_setting(http, ZAC, setting)
    assert json.loads(sent[-1].body) == setting


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
