"""Unit tests for the BRP and KvK helpers."""

import json

import pytest
import requests

from podiumd_tests.basisregistraties import BRP_PERSONEN
from podiumd_tests.basisregistraties import brp_gevonden
from podiumd_tests.basisregistraties import brp_persoon
from podiumd_tests.basisregistraties import kvk_foutcodes

PROXY = "https://api-proxy.example.test"
RAADPLEEG = "RaadpleegMetBurgerservicenummer"


def test_brp_persoon_posts_a_raadpleeg_query_and_returns_the_one_person(fake_http):
    sent = fake_http({f"POST {BRP_PERSONEN}": (200, {"type": RAADPLEEG, "personen": [{"leeftijd": 26}]})})
    assert brp_persoon(requests.Session(), PROXY, "999990019", ["leeftijd"]) == {"leeftijd": 26}
    query = {"type": RAADPLEEG, "burgerservicenummer": ["999990019"], "fields": ["leeftijd"]}
    assert json.loads(sent[0].body) == query


def test_brp_persoon_fails_when_the_bsn_finds_no_one(fake_http):
    fake_http({BRP_PERSONEN: (200, {"type": RAADPLEEG, "personen": []})})
    with pytest.raises(AssertionError, match="found 0 personen under BSN 999990019, expected 1"):
        brp_persoon(requests.Session(), PROXY, "999990019", ["leeftijd"])


def test_brp_gevonden_fails_on_an_answer_of_another_type(fake_http):
    fake_http({BRP_PERSONEN: (200, {"type": "ZoekMetPostcodeEnHuisnummer", "personen": []})})
    with pytest.raises(AssertionError, match=f"type ZoekMetPostcodeEnHuisnummer to a {RAADPLEEG} query"):
        brp_gevonden(requests.Session(), PROXY, {"type": RAADPLEEG})


def test_kvk_foutcodes_lists_the_codes_of_the_fout_list(response_factory):
    body = {"fout": [{"code": "IPD5200", "omschrijving": "Er zijn geen gegevens gevonden"}, {"code": "IPD0005"}]}
    assert kvk_foutcodes(response_factory(status=404, json_body=body)) == {"IPD5200", "IPD0005"}


def test_kvk_foutcodes_is_empty_without_a_fout_list(response_factory):
    assert kvk_foutcodes(response_factory(json_body={"resultaten": []})) == set()
