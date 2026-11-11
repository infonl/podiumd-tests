"""Unit tests for the ZAC REST helpers."""

import json

import pytest
import requests

from podiumd_tests import zac
from podiumd_tests.clients.api import ApiClient
from podiumd_tests.oidc import LOGIN_PATHS
from podiumd_tests.seed.registry import ResourceRegistry
from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import inrichtingscheck_problems

ZAC = "https://zac.test"


def test_create_zaak_reads_the_zaak_when_zac_answers_only_its_identificatie(fake_http):
    fake_http(
        {
            "POST /rest/zaken/zaak": (200, {"identificatie": "ZAAK-1"}),
            "GET /rest/zaken/zaak/id/ZAAK-1": (200, {"identificatie": "ZAAK-1", "uuid": "u-1"}),
        }
    )
    parameters = {"zaaktype": {"uuid": "zt"}, "defaultGroepId": "g"}
    zaak = create_zaak(requests.Session(), "https://zac.test", parameters, omschrijving="x")
    assert zaak["uuid"] == "u-1"


def _check(**fields):
    passing = {
        "statustypeIntakeAanwezig": True,
        "aantalInitiatorroltypen": 1,
        "aantalBehandelaarroltypen": 1,
        "besluittypeAanwezig": False,
        "resultaattypesMetVerplichtBesluit": [],
        "isZaakspecifiekeAutorisatieEigenschapAanwezig": False,
        "isZaakspecifiekeAutorisatieRoltypeAanwezig": False,
        "heeftWaarschuwingen": False,
        "valide": True,
    }
    return {**passing, **fields}


def test_inrichtingscheck_passes_without_the_optional_zaakspecifieke_autorisatie():
    assert inrichtingscheck_problems(_check()) == []


def test_inrichtingscheck_names_a_missing_behandelaar_roltype():
    assert inrichtingscheck_problems(_check(aantalBehandelaarroltypen=0, valide=False)) == [
        "aantalBehandelaarroltypen=0"
    ]


def test_inrichtingscheck_needs_a_besluittype_only_for_a_resultaattype_with_verplicht_besluit():
    check = _check(resultaattypesMetVerplichtBesluit=["Toegekend"], valide=False)
    assert inrichtingscheck_problems(check) == ["besluittypeAanwezig"]


def test_inrichtingscheck_fails_on_zacs_warnings():
    check = _check(isZaakspecifiekeAutorisatieRoltypeAanwezig=True, heeftWaarschuwingen=True)
    assert inrichtingscheck_problems(check) == ["heeftWaarschuwingen"]


def test_inrichtingscheck_falls_back_to_zacs_verdict():
    assert inrichtingscheck_problems(_check(valide=False)) == ["valide"]


def test_create_zaak_returns_the_answer_when_it_has_a_uuid(fake_http):
    sent = fake_http({"POST /rest/zaken/zaak": (200, {"uuid": "u-1"})})
    parameters = {"zaaktype": {"uuid": "zt"}, "defaultGroepId": "g"}
    assert create_zaak(requests.Session(), ZAC, parameters)["uuid"] == "u-1"
    body = json.loads(sent[0].body)["zaak"]
    assert (body["groep"], body["communicatiekanaal"]) == ({"id": "g", "naam": "g"}, "E-mail")


def test_read_zaak(fake_http):
    fake_http({"GET /rest/zaken/zaak/u-1": (200, {"uuid": "u-1"})})
    assert zac.read_zaak(requests.Session(), ZAC, "u-1") == {"uuid": "u-1"}


def parameters(identificatie, *, enabled=True, id_: int | None = 1):
    confirmation = {"enabled": enabled, "templateName": "t", "emailSender": {"mail": "x"}}
    return {"id": id_, "zaaktype": {"identificatie": identificatie}, "automaticEmailConfirmation": confirmation}


@pytest.mark.parametrize(
    ("found", "on"),
    [
        ([parameters("zt1"), parameters("zt1"), parameters("zt2", enabled=False)], True),
        ([parameters("zt1"), parameters("zt1", enabled=False)], False),
        ([parameters("zt1", id_=None)], False),
    ],
    ids=["every-version", "one-version-off", "only-without-parameters"],
)
def test_confirmation_on(fake_http, found, on):
    fake_http({"GET /rest/zaakafhandelparameters": (200, found)})
    assert zac.is_confirmation_on(requests.Session(), ZAC, "zt1") is on


def test_person_key_retries_once_with_a_fresh_lookup_on_410(fake_http, response_factory):
    fake_http({"PUT /rest/klanten/personen": (200, {"resultaten": [{"temporaryPersonId": "p1"}]})})
    statuses = iter([410, 200])
    sent_ids = []

    def send(betrokkene):
        sent_ids.append(betrokkene["temporaryPersonId"])
        return response_factory(status=next(statuses))

    assert zac.send_with_person(requests.Session(), ZAC, "999990755", send).status_code == 200
    assert sent_ids == ["p1", "p1"]


def test_productaanvraag_zaak_finds_the_zaak_by_kenmerk_and_cleanup_deletes_it(fake_http):
    zaken = [{"url": "https://oz.test/zaken/api/v1/zaken/1", "toelichting": "kenmerk OF-42"}, {"url": "z/2"}]
    sent = fake_http(
        {
            "GET /zaken/api/v1/zaken": (200, zaken),
            "GET /zaken/api/v1/zaakinformatieobjecten": (200, []),
            "DELETE /zaken/api/v1/zaken/1": (204, None),
        }
    )
    registry = ResourceRegistry("ptest-abc")
    openzaak = ApiClient(requests.Session(), "https://oz.test", {})
    assert zac.productaanvraag_zaak(openzaak, registry, "OF-42", timeout=0)["url"] == zaken[0]["url"]
    assert "startdatum__gte" in sent[0].url
    assert registry.cleanup() == []
    assert sent[-1].method == "DELETE"


def test_reindex_zaken_calls_zacs_internal_endpoint_in_the_pod(env_factory, fake_runner):
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "zac"}}]}))
    fake_runner.answers["exec deploy/zac"] = (0, "")
    zac.reindex_zaken(env_factory())
    assert "herindexeren/ZAAK" in fake_runner.calls[-1][-1]


def test_count_zaken_found(fake_http):
    sent = fake_http({"PUT /rest/zoeken/list": (200, {"totaal": 3})})
    assert zac.count_zaken_found(requests.Session(), ZAC, "Klacht") == 3
    assert json.loads(sent[0].body)["filters"] == {"ZAAKTYPE": {"values": ["Klacht"]}}


def test_zac_session_logs_in_through_keycloak(env_factory, profile_factory, monkeypatch):
    logins = []
    monkeypatch.setattr(zac, "form_login", lambda _http, url, user, password: logins.append((url, user, password)))
    zac.zac_session(env_factory(profile_factory(urls={"zac": ZAC})), "u", "p")
    assert logins == [(ZAC + LOGIN_PATHS["zac"], "u", "p")]


def test_zaak_listed_searches_by_identificatie_with_the_flags(fake_http):
    sent = fake_http({"PUT /rest/zoeken/list": (200, {"resultaten": [{"identificatie": "ZAAK-1"}]})})
    assert zac.is_zaak_listed(requests.Session(), ZAC, "ZAAK-1", alleenOpenstaandeZaken=True)
    assert not zac.is_zaak_listed(requests.Session(), ZAC, "ZAAK-2")
    body = json.loads(sent[0].body)
    assert body["zoeken"] == {"ZAAK_IDENTIFICATIE": "ZAAK-1"}
    assert body["alleenOpenstaandeZaken"] is True


def test_open_task_skips_completed_tasks_and_complete_task_sends_the_form_data(fake_http):
    tasks = [
        {"id": "t-1", "naam": "Intake", "status": "AFGEROND", "taakdata": {}},
        {"id": "t-2", "naam": "Intake", "status": "TOEGEKEND", "taakdata": {"bestaand": "x"}},
    ]
    sent = fake_http(
        {"GET /rest/taken/zaak/z-1": (200, tasks), "PATCH /rest/taken/complete": (200, {"status": "AFGEROND"})}
    )
    http = requests.Session()
    task = zac.open_task(http, "https://zac.example.test", "z-1", "Intake")
    assert task["id"] == "t-2"
    assert zac.complete_task(http, "https://zac.example.test", task, {"veld": "y"}) == {"status": "AFGEROND"}
    assert json.loads(sent[-1].body)["taakdata"] == {"bestaand": "x", "veld": "y"}


def test_user_event_runs_the_open_plan_item_of_the_action(fake_http):
    sent = fake_http(
        {
            "GET /rest/planitems/zaak/z1/userEventListenerPlanItems": (
                200,
                [{"id": "p1", "naam": "Intake afronden", "userEventListenerActie": "INTAKE_AFRONDEN"}],
            ),
            "POST /rest/planitems/doUserEventListenerPlanItem": (204, None),
        }
    )
    http = requests.Session()
    zac.user_event(http, ZAC, "z1", "INTAKE_AFRONDEN", zaakOntvankelijk=True)
    assert json.loads(sent[-1].body) == {
        "zaakUuid": "z1",
        "planItemInstanceId": "p1",
        "actie": "INTAKE_AFRONDEN",
        "zaakOntvankelijk": True,
    }
    with pytest.raises(AssertionError, match=r"offers no ZAAK_AFHANDELEN: \['Intake afronden'\]"):
        zac.user_event(http, ZAC, "z1", "ZAAK_AFHANDELEN")


def test_resultaattypen_are_those_of_the_zaaktype(fake_http):
    fake_http({"GET /rest/zaken/resultaattypes/zt1": (200, [{"id": "r1"}])})
    assert zac.resultaattypen(requests.Session(), ZAC, {"zaaktype": {"uuid": "zt1"}}) == [{"id": "r1"}]


def test_koppel_and_ontkoppel_send_zacs_link_data(fake_http):
    sent = fake_http({"PATCH /rest/zaken/zaak/koppel": (204, None), "PATCH /rest/zaken/zaak/ontkoppel": (204, None)})
    http = requests.Session()
    zaak, ander = {"uuid": "z1", "identificatie": "ZAAK-1"}, {"uuid": "z2", "identificatie": "ZAAK-2"}
    zac.koppel(http, ZAC, zaak, ander, "GERELATEERD")
    assert json.loads(sent[-1].body) == {"zaakUuid": "z1", "teKoppelenZaakUuid": "z2", "relatieType": "GERELATEERD"}
    zac.ontkoppel(http, ZAC, zaak, ander, "GERELATEERD", "reden")
    assert json.loads(sent[-1].body) == {
        "zaakUuid": "z1",
        "gekoppeldeZaakIdentificatie": "ZAAK-2",
        "relatieType": "GERELATEERD",
        "reden": "reden",
    }


def test_koppel_zoekresultaat_matches_the_uuid_not_the_identificatie(fake_http):
    deleted = {"id": "old", "identificatie": "ZAAK-2", "nietKoppelbaarReden": "AFGEHANDELD"}
    current = {"id": "z2", "identificatie": "ZAAK-2", "nietKoppelbaarReden": None}
    sent = fake_http(
        {"PUT /rest/zaken/gekoppelde-zaken/z1/zoek-koppelbare-zaken": (200, {"resultaten": [deleted, current]})}
    )
    zaak, ander = {"uuid": "z1"}, {"uuid": "z2", "identificatie": "ZAAK-2"}
    assert zac.koppel_zoekresultaat(requests.Session(), ZAC, zaak, ander, "DEELZAAK") == current
    assert json.loads(sent[-1].body)["relationType"] == "DEELZAAK"
    assert (
        zac.koppel_zoekresultaat(requests.Session(), ZAC, zaak, {"uuid": "z3", "identificatie": "ZAAK-3"}, "DEELZAAK")
        is None
    )


def test_besluit_calls_send_zacs_fields(fake_http):
    sent = fake_http(
        {
            "GET /rest/zaken/besluittypes/zt1": (200, [{"id": "bt1"}]),
            "POST /rest/zaken/besluit": (200, {"uuid": "b1"}),
            "DELETE /rest/health-check/ztc-cache": (200, "2026-11-11T12:00:00Z"),
        }
    )
    http, zaak = requests.Session(), {"uuid": "z1", "zaaktype": {"uuid": "zt1"}}
    besluittype = zac.besluittypen(http, ZAC, zaak)[0]
    zac.vastleggen_besluit(http, ZAC, zaak, besluittype, ingangsdatum="2026-11-11")
    assert json.loads(sent[-1].body) == {"zaakUuid": "z1", "besluittypeUuid": "bt1", "ingangsdatum": "2026-11-11"}
    zac.clear_ztc_cache(http, ZAC)
    assert sent[-1].method == "DELETE"


def test_send_mail_and_its_acknowledge_variant(fake_http):
    sent = fake_http(
        {
            "GET /rest/zaken/zaak/z1/afzender": (200, [{"mail": "noreply@example.test"}]),
            "POST /rest/mail/send/z1": (204, None),
            "POST /rest/mail/acknowledge/z1": (204, None),
        }
    )
    http, zaak = requests.Session(), {"uuid": "z1"}
    assert zac.afzenders(http, ZAC, zaak) == [{"mail": "noreply@example.test"}]
    zac.send_mail(http, ZAC, zaak, {"onderwerp": "x"})
    assert sent[-1].url.endswith("/rest/mail/send/z1")
    zac.send_mail(http, ZAC, zaak, {"onderwerp": "x"}, acknowledge=True)
    assert sent[-1].url.endswith("/rest/mail/acknowledge/z1")
