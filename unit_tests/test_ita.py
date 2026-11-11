"""Unit tests for ITA's calls on a contactverzoek and its lists."""

import json

from urllib.parse import parse_qs
from urllib.parse import urlsplit

import pytest
import requests

from podiumd_tests import ita
from podiumd_tests.responses import UnexpectedStatusError

ITA = "https://ita.example.test"
TAAK = {"uuid": "t-1", "aanleidinggevendKlantcontact": {"uuid": "k-1", "url": "https://ok/k-1"}}


def test_assign_to_me_posts_to_the_internetaak(fake_http):
    sent = fake_http({"POST /api/internetaken/t-1/aan-mij-toewijzen": (200, {})})
    ita.assign_to_me(requests.Session(), ITA, TAAK)
    assert [s.url for s in sent] == [f"{ITA}/api/internetaken/t-1/aan-mij-toewijzen"]


def test_answer_body_drops_the_nummer_and_links_the_partij():
    body = ita.answer_body(TAAK, {"nummer": "123", "onderwerp": "o"}, "p-1")
    assert body == {
        "interneTaakId": "t-1",
        "aanleidinggevendKlantcontactUuid": "k-1",
        "klantcontactRequest": {"onderwerp": "o"},
        "partijUuid": "p-1",
    }
    assert "partijUuid" not in ita.answer_body(TAAK, {})


def test_close_with_klantcontact_expects_created(fake_http):
    path = "/api/internetaken/close-with-klantcontact"
    sent = fake_http({path: (201, {"klantcontact": {"uuid": "k-2"}})})
    assert ita.close_with_klantcontact(requests.Session(), ITA, {"a": 1}) == {"klantcontact": {"uuid": "k-2"}}
    assert json.loads(sent[0].body) == {"a": 1}
    fake_http({path: (409, {"code": "UNEXPECTED_ERROR"})})
    with pytest.raises(UnexpectedStatusError):
        ita.close_with_klantcontact(requests.Session(), ITA, {})


@pytest.mark.parametrize(("afgerond", "query"), [(False, "afgerond=false"), (True, "afgerond=true")])
def test_my_internetaken_asks_open_or_afgerond(fake_http, afgerond, query):
    sent = fake_http({"/api/internetaken/aan-mij-toegewezen": (200, [{"uuid": "t-1"}])})
    assert ita.uuids(ita.my_internetaken(requests.Session(), ITA, afgerond=afgerond)) == ["t-1"]
    assert urlsplit(sent[0].url).query == query


def test_overview_reads_every_page(monkeypatch, response_factory):
    pages = {"1": {"results": [{"uuid": "a"}], "next": "https://ok/?page=2"}, "2": {"results": [{"uuid": "b"}]}}
    asked = []

    def get(_session, url, params):
        asked.append((url, params))
        return response_factory(json_body=pages[params["page"]])

    monkeypatch.setattr(requests.Session, "get", get)
    found = ita.afdeling_or_groep_historie(requests.Session(), ITA, "grp")
    assert ita.uuids(found) == ["a", "b"]
    assert asked[0] == (
        f"{ITA}/api/internetaken/afdelingen-groepen",
        {"naamActor": "grp", "afgerond": "true", "page": "1", "pageSize": "100"},
    )


def test_overview_refuses_a_list_past_itas_last_page(fake_http):
    sent = fake_http({"/api/internetaken": (200, {"results": [], "next": "https://ok/?page=x"})})
    with pytest.raises(LookupError, match="more than 10000"):
        ita.overview(requests.Session(), f"{ITA}/api/internetaken")
    assert len(sent) == ita.MAX_PAGES
    assert parse_qs(urlsplit(sent[-1].url).query)["page"] == [str(ita.MAX_PAGES)]


def test_my_afdelingen_and_groepen_returns_the_names(fake_http):
    fake_http({"/api/gebruiker-groepen-and-afdelingen": (200, ["afd", "grp"])})
    assert ita.my_afdelingen_and_groepen(requests.Session(), ITA) == ["afd", "grp"]


def test_make_contactverzoek_cleans_up_itas_logboek(monkeypatch):
    made = []
    monkeypatch.setattr(ita, "make_klantcontact", lambda _ok, _reg: {"uuid": "k-1"})
    monkeypatch.setattr(ita, "make_internetaak", lambda _ok, _reg, kc, actoren: made.append((kc, actoren)) or TAAK)
    monkeypatch.setattr(ita, "clean_up_logboek", lambda _obj, _reg, soort, uuid: made.append((soort, uuid)))
    assert ita.make_contactverzoek(None, None, None, "logboek", [{"uuid": "a"}]) is TAAK  # pyright: ignore[reportArgumentType]
    assert made == [({"uuid": "k-1"}, [{"uuid": "a"}]), ("logboek", "t-1")]
