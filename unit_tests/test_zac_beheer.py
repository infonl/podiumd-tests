"""Unit tests for ZAC's beheer of referentietabellen."""

import json

import pytest
import requests

from podiumd_tests import zac_beheer
from podiumd_tests.seed.registry import ResourceRegistry

ZAC = "https://zac.example.test"
RUN = "ptest-2611112000abcd"
TABELLEN = "/rest/referentietabellen"


def test_create_referentietabel_sends_a_run_tagged_upper_case_code_and_cleanup_deletes_it(fake_http):
    sent = fake_http({f"POST {TABELLEN}": (200, {"id": 7, "code": "C"}), f"DELETE {TABELLEN}/7": (404, {})})
    registry = ResourceRegistry(RUN)
    assert zac_beheer.create_referentietabel(requests.Session(), ZAC, registry, ["Een"]) == {"id": 7, "code": "C"}
    body = json.loads(sent[0].body)
    assert body["code"].startswith(f"{RUN}-ZAC-".upper())
    assert (body["name"], body["values"]) == (body["code"], [{"name": "Een"}])
    registry.cleanup()
    assert sent[-1].method == "DELETE"


def test_update_referentietabel_sends_name_code_and_values(fake_http):
    sent = fake_http({f"PUT {TABELLEN}/7": (200, {})})
    tabel = {"id": 7, "code": "C", "name": "N", "values": [], "systemTable": False}
    zac_beheer.update_referentietabel(requests.Session(), ZAC, tabel, [{"name": "Een"}])
    assert json.loads(sent[0].body) == {"name": "N", "code": "C", "values": [{"name": "Een"}]}


BALIE = {"id": 1, "name": "Balie", "systemValue": False}
E_FORMULIER = {"id": 2, "name": "E-formulier", "systemValue": True}
TABEL = {"id": 5, "code": "K", "name": "Kanaal", "values": [BALIE, E_FORMULIER]}


@pytest.mark.parametrize(
    ("current", "puts"),
    [
        ([BALIE, E_FORMULIER], []),
        ([E_FORMULIER, BALIE], []),
        ([BALIE], [[BALIE, {**E_FORMULIER, "id": None}]]),
    ],
)
def test_guard_referentietabel_saves_the_table_back_only_when_its_values_changed(fake_http, current, puts):
    sent = fake_http({f"GET {TABELLEN}/code/K": (200, {**TABEL, "values": current}), f"PUT {TABELLEN}/5": (200, {})})
    registry = ResourceRegistry(RUN)
    zac_beheer.guard_referentietabel(requests.Session(), ZAC, registry, TABEL)
    registry.cleanup()
    assert [json.loads(request.body)["values"] for request in sent if request.method == "PUT"] == puts
