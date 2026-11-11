"""Unit tests for ZAC's betrokkenen and initiator helpers."""

import json

import requests

from podiumd_tests import zac_betrokkenen

ZAC = "https://zac.example.test"
ZAAK = {"uuid": "z1", "zaaktype": {"uuid": "zt1"}}


def test_betrokkene_roltype_matches_the_naam_prefix_and_add_sends_it(fake_http):
    roltypen = [{"uuid": "r1", "naam": "Bewindvoerder e2e"}, {"uuid": "r2", "naam": "Belanghebbende e2e"}]
    sent = fake_http(
        {
            "GET /rest/klanten/roltype/zt1/betrokkene": (200, roltypen),
            "POST /rest/zaken/betrokkene": (200, {}),
            "GET /rest/zaken/zaak/z1/betrokkene": (200, [{"rolid": "b1"}]),
            "DELETE /rest/zaken/betrokkene/b1": (200, {}),
        }
    )
    http = requests.Session()
    roltype = zac_betrokkenen.betrokkene_roltype(http, ZAC, ZAAK, "belanghebbende")
    assert roltype["uuid"] == "r2"
    zac_betrokkenen.add_betrokkene(http, ZAC, ZAAK, roltype, {"type": "BSN"})
    assert json.loads(sent[-1].body) == {
        "zaakUUID": "z1",
        "roltypeUUID": "r2",
        "roltoelichting": "podiumd-tests",
        "betrokkeneIdentificatie": {"type": "BSN"},
    }
    betrokkene = zac_betrokkenen.betrokkenen(http, ZAC, ZAAK)[0]
    zac_betrokkenen.ontkoppel_betrokkene(http, ZAC, betrokkene, "weg")
    assert json.loads(sent[-1].body) == {"reden": "weg"}


def test_initiator_is_changed_with_an_optional_toelichting_and_ontkoppeld_with_a_reden(fake_http):
    sent = fake_http({"PATCH /rest/zaken/initiator": (200, {}), "DELETE /rest/zaken/z1/initiator": (200, {})})
    http = requests.Session()
    zac_betrokkenen.wijzig_initiator(http, ZAC, ZAAK, {"type": "VN"}, None)
    assert json.loads(sent[-1].body) == {"zaakUUID": "z1", "betrokkeneIdentificatie": {"type": "VN"}}
    zac_betrokkenen.wijzig_initiator(http, ZAC, ZAAK, {"type": "VN"}, "anders")
    assert json.loads(sent[-1].body)["toelichting"] == "anders"
    zac_betrokkenen.ontkoppel_initiator(http, ZAC, ZAAK, "weg")
    assert json.loads(sent[-1].body) == {"reden": "weg"}
