"""Unit tests for the BRP and KvK helpers."""

import json

import pytest
import requests

from podiumd_tests.basisregistraties import Registers
from podiumd_tests.basisregistraties import api_proxy_registers
from podiumd_tests.basisregistraties import app_registers
from podiumd_tests.basisregistraties import brp_gevonden
from podiumd_tests.basisregistraties import brp_persoon
from podiumd_tests.basisregistraties import kvk_foutcodes
from podiumd_tests.basisregistraties import outway_registers

PROXY = "https://api-proxy.example.test"
OUTWAY = "http://frankgateway-outway.podiumd.svc.cluster.local:9080"
REGISTERS = api_proxy_registers(PROXY)
BRP_PERSONEN = "/haalcentraal/api/brp/personen"
RAADPLEEG = "RaadpleegMetBurgerservicenummer"


def test_brp_persoon_posts_a_raadpleeg_query_and_returns_the_one_person(fake_http):
    sent = fake_http({f"POST {BRP_PERSONEN}": (200, {"type": RAADPLEEG, "personen": [{"leeftijd": 26}]})})
    assert brp_persoon(requests.Session(), REGISTERS, "999990019", ["leeftijd"]) == {"leeftijd": 26}
    query = {"type": RAADPLEEG, "burgerservicenummer": ["999990019"], "fields": ["leeftijd"]}
    assert json.loads(sent[0].body) == query


def test_brp_persoon_fails_when_the_bsn_finds_no_one(fake_http):
    fake_http({BRP_PERSONEN: (200, {"type": RAADPLEEG, "personen": []})})
    with pytest.raises(AssertionError, match="found 0 personen under BSN 999990019, expected 1"):
        brp_persoon(requests.Session(), REGISTERS, "999990019", ["leeftijd"])


def test_brp_gevonden_fails_on_an_answer_of_another_type(fake_http):
    fake_http({BRP_PERSONEN: (200, {"type": "ZoekMetPostcodeEnHuisnummer", "personen": []})})
    with pytest.raises(AssertionError, match=f"type ZoekMetPostcodeEnHuisnummer to a {RAADPLEEG} query"):
        brp_gevonden(requests.Session(), REGISTERS, {"type": RAADPLEEG})


def test_kvk_foutcodes_lists_the_codes_of_the_fout_list(response_factory):
    body = {"fout": [{"code": "IPD5200", "omschrijving": "Er zijn geen gegevens gevonden"}, {"code": "IPD0005"}]}
    assert kvk_foutcodes(response_factory(status=404, json_body=body)) == {"IPD5200", "IPD0005"}


def test_kvk_foutcodes_is_empty_without_a_fout_list(response_factory):
    assert kvk_foutcodes(response_factory(json_body={"resultaten": []})) == set()


def test_api_proxy_registers_are_on_its_own_paths():
    assert api_proxy_registers(PROXY) == Registers(
        f"{PROXY}/haalcentraal/api/brp", f"{PROXY}/lvbag/individuelebevragingen/v2", PROXY
    )


def test_outway_registers_are_under_the_apps_prefix():
    assert outway_registers(OUTWAY, "openformulieren") == Registers(
        f"{OUTWAY}/forms/brp", f"{OUTWAY}/forms/bag", f"{OUTWAY}/forms/kvk"
    )


def test_app_registers_prefer_the_outway_once_it_routes_per_app(fake_http):
    fake_http({"/zac/brp/personen": (405, {"error_msg": "Method Not Allowed"})})
    urls = {"frankgateway": OUTWAY, "api-proxy": PROXY}
    assert app_registers(requests.Session(), urls, {"frankgateway", "api-proxy"}) == outway_registers(OUTWAY, "zac")


def test_app_registers_fall_back_to_the_api_proxy_without_per_app_routes(fake_http):
    fake_http({"/zac/brp/personen": (404, {"error_msg": "404 Route Not Found"})})
    urls = {"frankgateway": OUTWAY, "api-proxy": PROXY}
    assert app_registers(requests.Session(), urls, {"frankgateway", "api-proxy"}) == REGISTERS


def test_app_registers_are_none_without_either_gateway():
    assert app_registers(requests.Session(), {}, set()) is None
