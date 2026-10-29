"""Unit tests for the KISS and ITA helpers of the klantcontactmedewerker."""

import json

from types import SimpleNamespace

import pytest
import requests

from podiumd_tests import kcc
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.kcc import KENNIS_URL
from podiumd_tests.kcc import expect_ita_group_access_bug
from podiumd_tests.kcc import ita_detail_text
from podiumd_tests.kcc import kcc_login
from podiumd_tests.kcc import kennisartikel_data
from podiumd_tests.kcc import kiss_klantcontact
from podiumd_tests.kcc import kiss_register
from podiumd_tests.kcc import kiss_sync_cronjob
from podiumd_tests.kcc import vac_data
from podiumd_tests.seed.registry import ResourceRegistry

KISS = "https://kiss.example.test"
REGISTERS = {
    "systemen": [
        {"identifier": "oud", "isDefault": False, "registryVersion": "OpenKlant2"},
        {"identifier": "esuite", "isDefault": False, "registryVersion": "OpenKlant1"},
        {"identifier": "ok-1", "isDefault": True, "registryVersion": "OpenKlant2"},
    ]
}


def test_kcc_login_uses_the_kcc_test_user(monkeypatch, page_env):
    logins = []
    monkeypatch.setattr(kcc, "challenge_login", lambda _p, _e, url, user, pw: logins.append((url, user, pw)))
    kcc_login(None, page_env(), "ita")  # pyright: ignore[reportArgumentType]
    assert logins == [("https://ita.example.test", KCC.username, f"pw-{KCC.store_key}")]


def test_kiss_register_picks_the_default_open_klant_2_systeem(fake_http):
    fake_http({"/api/environment/registers": (200, REGISTERS)})
    assert kiss_register(requests.Session(), KISS) == {"systemIdentifier": "ok-1"}


def test_kiss_register_skips_without_an_open_klant_2_systeem(fake_http):
    esuite = {"systemen": [{"identifier": "esuite", "isDefault": True, "registryVersion": "OpenKlant1"}]}
    fake_http({"/api/environment/registers": (200, esuite)})
    with pytest.raises(pytest.skip.Exception, match="no Open Klant 2 register"):
        kiss_register(requests.Session(), KISS)


def test_kiss_klantcontact_registers_cleanup_in_open_klant(fake_http):
    sent = fake_http(
        {
            "/api/environment/registers": (200, REGISTERS),
            "POST /api/klantinteracties/api/v1/klantcontacten": (201, {"url": "https://ok/kc/1", "uuid": "1"}),
        }
    )
    deleted = []
    openklant = SimpleNamespace(delete=deleted.append, get=lambda path: {"path": path})
    registry = ResourceRegistry("ptest-run")
    assert kiss_klantcontact(requests.Session(), KISS, openklant, registry, {"kanaal": "telefoon"}) == {  # pyright: ignore[reportArgumentType]
        "path": "klantcontacten/1"
    }
    assert sent[1].headers["systemIdentifier"] == "ok-1"
    registry.cleanup()
    assert deleted == ["https://ok/kc/1"]


def test_ita_detail_text_is_the_json_of_the_internetaak(fake_http):
    fake_http({"/api/internetaken/7": (200, {"vraag": "Wanneer?"})})
    assert json.loads(ita_detail_text(requests.Session(), "https://ita", {"nummer": 7})) == {"vraag": "Wanneer?"}


@pytest.mark.parametrize(("version", "xfail"), [((3, 3, 3), True), ((3, 3, 4), False), (None, False)])
def test_ita_group_access_bug_is_expected_before_3_3_4(monkeypatch, version, xfail):
    monkeypatch.setattr(kcc, "component_versions", lambda _env, _c: {} if version is None else {"ita": version})
    markers = []
    expect_ita_group_access_bug(SimpleNamespace(applymarker=markers.append), None)  # pyright: ignore[reportArgumentType]
    assert bool(markers) is xfail


def test_kiss_sync_cronjob_finds_the_cronjob_of_the_source():
    env = SimpleNamespace(
        items=lambda _kind: [{"metadata": {"name": n}} for n in ("contact-vac-sync", "contact-kennisbank-sync")]
    )
    assert kiss_sync_cronjob(env, "kennisbank") == "contact-kennisbank-sync"  # pyright: ignore[reportArgumentType]


def test_search_content_carries_the_title():
    assert vac_data("Afval?")["vraag"] == "Afval?"
    artikel = kennisartikel_data("Afval ophalen")
    assert artikel["url"] == KENNIS_URL + "Afval%20ophalen"
    assert artikel["vertalingen"][0]["titel"] == "Afval ophalen"  # pyright: ignore[reportIndexIssue]
