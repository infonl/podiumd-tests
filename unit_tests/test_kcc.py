"""Unit tests for the KISS and ITA helpers of the klantcontactmedewerker."""

import json

from datetime import UTC
from datetime import datetime
from types import SimpleNamespace

import pytest
import requests

from podiumd_tests import kcc
from podiumd_tests import workloads
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.kcc import KENNIS_URL
from podiumd_tests.kcc import LOGBOEK_HINT
from podiumd_tests.kcc import add_klantcontact
from podiumd_tests.kcc import expect_ita_group_access_bug
from podiumd_tests.kcc import ita_detail_text
from podiumd_tests.kcc import kcc_login
from podiumd_tests.kcc import kennisartikel_data
from podiumd_tests.kcc import kiss_klantcontact
from podiumd_tests.kcc import kiss_register
from podiumd_tests.kcc import kiss_search_hits
from podiumd_tests.kcc import kiss_sync_cronjob
from podiumd_tests.kcc import kiss_website_crawlers
from podiumd_tests.kcc import vac_data
from podiumd_tests.responses import UnexpectedStatusError
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
    monkeypatch.setattr(workloads, "component_versions", lambda _env, _c: {} if version is None else {"ita": version})
    markers = []
    expect_ita_group_access_bug(SimpleNamespace(applymarker=markers.append), None)  # pyright: ignore[reportArgumentType]
    assert bool(markers) is xfail


def test_kiss_sync_cronjob_finds_the_cronjob_of_the_source():
    env = SimpleNamespace(
        items=lambda _kind: [{"metadata": {"name": n}} for n in ("contact-vac-sync", "contact-kennisbank-sync")]
    )
    assert kiss_sync_cronjob(env, "kennisbank") == "contact-kennisbank-sync"  # pyright: ignore[reportArgumentType]


def test_kiss_website_crawlers_reads_the_url_of_each_crawler():
    names = ("contact-vac-sync", "contact-crawler-website-0", "contact-crawler-index-template")
    secrets = {("contact-crawler-website-0", "crawler.yml"): "domains:\n  - url: https://www.dimpact.nl\n"}
    env = SimpleNamespace(
        items=lambda _kind: [{"metadata": {"name": n}} for n in names],
        kube=SimpleNamespace(secret_value=lambda name, key: secrets[name, key]),
    )
    assert kiss_website_crawlers(env) == {"contact-crawler-website-0": "https://www.dimpact.nl"}  # pyright: ignore[reportArgumentType]


def test_kiss_search_hits_posts_the_query_to_all_sources(response_factory):
    posted = []

    def post(url, json):
        posted.append((url, json))
        return response_factory(json_body={"hits": {"hits": [{"_source": {"url_host": "www.dimpact.nl"}}]}})

    hits = kiss_search_hits(SimpleNamespace(post=post), KISS, "dimpact")  # pyright: ignore[reportArgumentType]
    assert hits == [{"_source": {"url_host": "www.dimpact.nl"}}]
    assert posted == [(f"{KISS}/api/search", {"query": "dimpact", "page": 1, "filters": []})]


def test_search_content_carries_the_title():
    assert vac_data("Afval?")["vraag"] == "Afval?"
    artikel = kennisartikel_data("Afval ophalen")
    assert artikel["url"] == f"{KENNIS_URL}Afval%20ophalen"
    assert artikel["vertalingen"][0]["titel"] == "Afval ophalen"  # pyright: ignore[reportIndexIssue]


ITA = "https://ita.example.test"
ADD = "/api/klantcontacten/add-klantcontact"
LOGBOEK_409 = {
    "code": "UNEXPECTED_ERROR",
    "message": "Response status code does not indicate success: 403 (Forbidden).",
}


def test_add_klantcontact_names_the_edge_cause_of_objectens_403(fake_http):
    fake_http({ADD: (409, LOGBOEK_409)})
    with pytest.raises(UnexpectedStatusError, match="bufferRequestBody"):
        add_klantcontact(requests.Session(), ITA, {})


def test_add_klantcontact_other_failures_get_no_hint(fake_http):
    fake_http({ADD: (500, {"detail": "boom"})})
    with pytest.raises(UnexpectedStatusError) as raised:
        add_klantcontact(requests.Session(), ITA, {})
    assert LOGBOEK_HINT not in str(raised.value)


def test_add_klantcontact_returns_the_response(fake_http):
    fake_http({ADD: (201, {})})
    assert add_klantcontact(requests.Session(), ITA, {}).status_code == 201


@pytest.mark.parametrize(("answer", "hours"), [((0, "72\n"), (72, 72)), ((1, ""), (48, 6)), ((0, "soon\n"), (48, 6))])
def test_ita_urgency_hours_fall_back_to_itas_defaults(env_factory, fake_runner, monkeypatch, answer, hours):
    env = env_factory()
    monkeypatch.setattr(type(env), "deployment_for", lambda _self, _component: "ita-web")
    fake_runner.answers["printenv Urgentie__"] = answer
    assert (kcc.ita_afhandeltermijn_hours(env), kcc.ita_bijna_verlopen_hours(env)) == hours


MONDAY_10 = datetime(2026, 11, 2, 10, tzinfo=UTC)


@pytest.mark.parametrize(
    ("moment", "hours", "expected"),
    [
        (MONDAY_10, 0, MONDAY_10),
        (MONDAY_10, 5, datetime(2026, 11, 2, 5, tzinfo=UTC)),
        (MONDAY_10, 48, datetime(2026, 10, 29, 10, tzinfo=UTC)),  # Friday and Thursday, not the weekend
        (datetime(2026, 11, 1, 12, tzinfo=UTC), 1, datetime(2026, 10, 30, 23, tzinfo=UTC)),  # from a Sunday
    ],
)
def test_weekday_hours_before_skips_the_weekend(moment, hours, expected):
    assert kcc.weekday_hours_before(moment, hours) == expected
