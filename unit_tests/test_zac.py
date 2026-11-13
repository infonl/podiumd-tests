"""Unit tests for the ZAC REST helpers."""

import functools
import json

from datetime import date

import pytest
import requests

from podiumd_tests import zac
from podiumd_tests import zac_taken
from podiumd_tests.clients.api import ApiClient
from podiumd_tests.oidc import LOGIN_PATHS
from podiumd_tests.responses import UnexpectedStatusError
from podiumd_tests.seed.registry import ResourceRegistry
from podiumd_tests.wait import Clock
from podiumd_tests.wait import wait_until
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


def test_zaak_status_is_the_omschrijving_zac_shows(fake_http):
    fake_http({"GET /rest/zaken/zaak/u-1": (200, {"uuid": "u-1", "status": {"naam": "Intake"}})})
    assert zac.zaak_status(requests.Session(), ZAC, {"uuid": "u-1"}) == "Intake"


@pytest.mark.parametrize(("status", "expected"), [(200, True), (403, False), (401, False)])
def test_can_open_zaak_is_true_only_for_200(fake_http, status, expected):
    fake_http({"GET /rest/zaken/zaak/u-1": (status, {})})
    assert zac.can_open_zaak(requests.Session(), ZAC, {"uuid": "u-1"}) is expected


def test_can_open_zaak_raises_on_another_status(fake_http):
    fake_http({"GET /rest/zaken/zaak/u-1": (500, {})})
    with pytest.raises(UnexpectedStatusError):
        zac.can_open_zaak(requests.Session(), ZAC, {"uuid": "u-1"})


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


def test_mail_address_of_gemeente_is_zacs_gemeente_mail(env_factory, fake_runner):
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "zac"}}]}))
    fake_runner.answers["printenv GEMEENTE_MAIL"] = (0, "noreply@gemeente.example\n")
    env = env_factory()
    assert zac.mail_address(env, "GEMEENTE") == "noreply@gemeente.example"
    assert fake_runner.calls[-1][-2:] == ["printenv", "GEMEENTE_MAIL"]
    assert zac.mail_address(env, "zaken@gemeente.example") == "zaken@gemeente.example"


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


def test_notificatie_names_the_resource_as_main_object_with_the_kenmerken():
    deleted = zac.notificatie("zaken", "zaak", "https://oz.test/zaken/z1", "destroy", zaaktype="zt")
    assert {key: value for key, value in deleted.items() if key != "aanmaakdatum"} == {
        "kanaal": "zaken",
        "hoofdObject": "https://oz.test/zaken/z1",
        "resource": "zaak",
        "resourceUrl": "https://oz.test/zaken/z1",
        "actie": "destroy",
        "kenmerken": {"zaaktype": "zt"},
    }
    assert str(deleted["aanmaakdatum"]).endswith("Z")


def test_reindex_zaken_calls_zacs_internal_endpoint_in_the_pod(env_factory, fake_runner):
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "zac"}}]}))
    fake_runner.answers["exec deploy/zac"] = (0, "")
    zac.reindex_zaken(env_factory())
    assert "herindexeren/ZAAK" in fake_runner.calls[-1][-1]


def test_reindex_zaken_in_the_background_waits_for_its_end_in_zacs_log(env_factory, fake_runner):
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "zac"}}]}))
    fake_runner.answers["exec deploy/zac"] = (0, "202")
    fake_runner.answers["logs deployment/zac"] = (0, "INFO [ZAAK] Reindexing finished. Reindexed: 3 / 3")
    zac.reindex_zaken(env_factory())
    assert "logs" in fake_runner.calls[-1]


def test_count_zaken_found(fake_http):
    sent = fake_http({"PUT /rest/zoeken/list": (200, {"totaal": 3})})
    assert zac.count_zaken_found(requests.Session(), ZAC, "Klacht") == 3
    assert json.loads(sent[0].body)["filters"] == {"ZAAKTYPE": {"values": ["Klacht"]}}


def test_search_all_reads_every_page_of_rows(fake_http):
    sent = fake_http({"PUT /rest/zoeken/list": (200, {"totaal": 5, "resultaten": [{"id": "z1"}, {"id": "z2"}]})})
    found = zac.search_all(requests.Session(), ZAC, 2, type="ZAAK")
    assert len(found) == 6
    assert [json.loads(request.body)["page"] for request in sent] == [0, 1, 2]
    assert {json.loads(request.body)["rows"] for request in sent} == {2}


def test_search_all_reads_one_page_when_nothing_is_found(fake_http):
    sent = fake_http({"PUT /rest/zoeken/list": (200, {"totaal": 0, "resultaten": []})})
    assert zac.search_all(requests.Session(), ZAC, 25, type="ZAAK") == []
    assert len(sent) == 1


def test_zac_session_logs_in_through_keycloak(env_factory, profile_factory, monkeypatch):
    logins = []
    monkeypatch.setattr(zac, "form_login", lambda _http, url, user, password: logins.append((url, user, password)))
    zac.zac_session(env_factory(profile_factory(urls={"zac": ZAC})), "u", "p")
    assert logins == [(ZAC + LOGIN_PATHS["zac"], "u", "p")]


def test_zaak_listed_searches_by_identificatie_with_the_flags_and_matches_the_uuid(fake_http):
    sent = fake_http({"PUT /rest/zoeken/list": (200, {"resultaten": [{"id": "z1", "identificatie": "ZAAK-1"}]})})
    assert zac.is_zaak_listed(
        requests.Session(), ZAC, {"uuid": "z1", "identificatie": "ZAAK-1"}, alleenOpenstaandeZaken=True
    )
    # A deleted zaak in ZAC's index with the same identificatie.
    assert not zac.is_zaak_listed(requests.Session(), ZAC, {"uuid": "z2", "identificatie": "ZAAK-1"})
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
    task = zac_taken.open_task(http, "https://zac.example.test", "z-1", "Intake")
    assert task["id"] == "t-2"
    assert zac_taken.complete_task(http, "https://zac.example.test", task, {"veld": "y"}) == {"status": "AFGEROND"}
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


def test_activate_human_tasks_switches_every_one_on_with_its_fields(fake_http):
    tasks = [
        {"actief": False, "planItemDefinition": {"id": "GOEDKEUREN"}, "doorlooptijd": None},
        {"actief": False, "planItemDefinition": {"id": "ADVIES_INTERN"}, "referentieTabellen": [{"veld": "ADVIES"}]},
    ]
    parameters = {"id": 7, "zaaktype": {"uuid": "zt1"}, "humanTaskParameters": tasks}
    sent = fake_http(
        {
            "GET /rest/zaakafhandelparameters/zt1": (200, parameters),
            "PUT /rest/zaakafhandelparameters": (200, {"id": 7}),
        }
    )
    assert zac_taken.activate_human_tasks(requests.Session(), ZAC, "zt1", GOEDKEUREN={"doorlooptijd": 10}) == {"id": 7}
    saved = json.loads(sent[-1].body)
    assert saved["id"] == 7
    assert saved["humanTaskParameters"] == [
        {"actief": True, "planItemDefinition": {"id": "GOEDKEUREN"}, "doorlooptijd": 10},
        {"actief": True, "planItemDefinition": {"id": "ADVIES_INTERN"}, "referentieTabellen": [{"veld": "ADVIES"}]},
    ]


def test_doorlooptijd_end_counts_days_from_today():
    assert zac_taken.doorlooptijd_end(0) == date.today().isoformat()  # noqa: DTZ011  # ZAC's local date


def test_start_human_task_waits_until_zac_offers_it_and_starts_it_without_a_mail(fake_http, monkeypatch):
    offers = iter([[], [{"id": "p9", "naam": "Goedkeuren"}]])
    monkeypatch.setattr(zac_taken, "human_tasks_offered", lambda *_args: next(offers))
    monkeypatch.setattr(zac_taken, "wait_until", functools.partial(wait_until, clock=Clock(sleep=lambda _s: None)))
    sent = fake_http({"POST /rest/planitems/doHumanTaskPlanItem": (204, None)})
    zaak = {"uuid": "z1", "identificatie": "ZAAK-1"}
    response = zac_taken.start_human_task(requests.Session(), ZAC, zaak, "Goedkeuren", "g1", fataledatum="2026-12-01")
    assert response.status_code == 204
    assert json.loads(sent[-1].body) == {
        "planItemInstanceId": "p9",
        "groep": {"id": "g1", "naam": "g1"},
        "taakdata": {},
        "taakStuurGegevens": {"sendMail": False},
        "fataledatum": "2026-12-01",
    }
    monkeypatch.setattr(zac_taken, "human_tasks_offered", lambda *_args: [{"id": "p9", "naam": "Goedkeuren"}])
    zac_taken.start_human_task(requests.Session(), ZAC, zaak, "Goedkeuren", None)
    assert json.loads(sent[-1].body)["groep"] is None


def test_started_taak_starts_it_for_the_behandelaar_and_returns_the_open_task(fake_http, monkeypatch):
    monkeypatch.setattr(zac_taken, "human_tasks_offered", lambda *_args: [{"id": "p9", "naam": "Goedkeuren"}])
    sent = fake_http(
        {
            "POST /rest/planitems/doHumanTaskPlanItem": (204, None),
            "GET /rest/taken/zaak/z1": (200, [{"id": "t1", "naam": "Goedkeuren", "status": "TOEGEKEND"}]),
        }
    )
    zaak = {"uuid": "z1", "identificatie": "ZAAK-1"}
    taak = zac_taken.started_taak(requests.Session(), ZAC, zaak, "Goedkeuren", ("g1", "bob"), toelichting="t")
    assert taak["id"] == "t1"
    started = json.loads(sent[0].body)
    assert (started["medewerker"], started["toelichting"]) == ({"id": "bob", "naam": "bob"}, "t")


def test_taak_historie_lists_zacs_answer(fake_http):
    fake_http({"GET /rest/taken/t1/historie": (200, [{"attribuutLabel": "taak.status"}])})
    assert zac_taken.taak_historie(requests.Session(), ZAC, {"id": "t1"}) == [{"attribuutLabel": "taak.status"}]


def test_human_tasks_and_user_events_offered_are_zacs_plan_items(fake_http):
    fake_http(
        {
            "GET /rest/planitems/zaak/z1/humanTaskPlanItems": (200, [{"naam": "Goedkeuren"}]),
            "GET /rest/planitems/zaak/z1/userEventListenerPlanItems": (200, [{"userEventListenerActie": "X"}]),
        }
    )
    http = requests.Session()
    assert zac_taken.human_tasks_offered(http, ZAC, {"uuid": "z1"}) == [{"naam": "Goedkeuren"}]
    assert zac.user_events_offered(http, ZAC, "z1") == [{"userEventListenerActie": "X"}]


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


def test_attempt_zaak_finds_the_zaken_by_omschrijving_and_cleanup_deletes_them(fake_http):
    zaken = [
        {"uuid": "1", "identificatie": "ZAAK-1", "omschrijving": "ptest-x"},
        {"uuid": "2", "identificatie": "ZAAK-2", "omschrijving": "ander"},
    ]
    sent = fake_http(
        {
            "POST /rest/zaken/zaak": (400, {"message": "refused"}),
            "GET /zaken/api/v1/zaken": (200, zaken),
            "GET /rest/zaken/zaak/1": (404, None),
            "GET /zaken/api/v1/zaakinformatieobjecten": (200, []),
            "DELETE /zaken/api/v1/zaken/1": (204, None),
        }
    )
    registry = ResourceRegistry("ptest-abc")
    openzaak = ApiClient(requests.Session(), "https://oz.test", {})
    body = {"zaak": {"omschrijving": "ptest-x"}}
    response, created = zac.attempt_zaak(requests.Session(), ZAC, openzaak, registry, body)
    assert (response.status_code, created) == (400, ["ZAAK-1"])
    assert registry.cleanup() == []
    assert [request.method for request in sent][-1] == "DELETE"


def test_zaak_historie_lists_zacs_answer_and_one_attribuut_of_it(fake_http):
    lines = [
        {"actie": "AANGEMAAKT", "attribuutLabel": "zaak"},
        {"attribuutLabel": "toelichting", "oudeWaarde": "a", "nieuweWaarde": "b", "toelichting": "r"},
    ]
    fake_http({"GET /rest/zaken/zaak/z1/historie": (200, lines)})
    assert zac.zaak_historie(requests.Session(), ZAC, {"uuid": "z1"}) == lines
    assert zac.attribuut_historie(requests.Session(), ZAC, {"uuid": "z1"}, "toelichting") == [("a", "b", "r")]


def test_bag_object_and_the_zaak_bag_objecten_are_read_from_zac(fake_http):
    fake_http(
        {
            "GET /rest/bag/ADRES/a1": (200, {"identificatie": "a1", "bagObjectType": "ADRES"}),
            "GET /rest/bag/zaak/z1": (200, [{"zaakobject": {"identificatie": "a1"}}]),
        }
    )
    http = requests.Session()
    assert zac.bag_object(http, ZAC, "ADRES", "a1") == {"identificatie": "a1", "bagObjectType": "ADRES"}
    assert zac.zaak_bag_objecten(http, ZAC, {"uuid": "z1"}) == [{"zaakobject": {"identificatie": "a1"}}]


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


def test_recorded_besluit_is_deleted_at_cleanup(fake_http):
    url = "https://oz.test/besluiten/api/v1/besluiten/b1"
    sent = fake_http(
        {
            "POST /rest/zaken/besluit": (200, {"url": url, "identificatie": "BESLUIT-1"}),
            "GET /besluiten/api/v1/besluitinformatieobjecten": (200, []),
            "DELETE /besluiten/api/v1/besluiten/b1": (204, None),
        }
    )
    registry = ResourceRegistry("ptest-abc")
    openzaak = ApiClient(requests.Session(), "https://oz.test", {})
    zaak = {"uuid": "z1"}
    zac.recorded_besluit(requests.Session(), ZAC, openzaak, registry, zaak, {"id": "bt1"})
    assert set(json.loads(sent[0].body)) == {"zaakUuid", "besluittypeUuid", "ingangsdatum", "toelichting"}
    assert registry.cleanup() == []
    assert f"{sent[-1].method} {sent[-1].url}" == f"DELETE {url}"


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


def test_afhandelen_and_afsluiten_use_a_resultaattype_without_besluit(fake_http):
    sent = fake_http(
        {
            "GET /rest/zaken/resultaattypes/zt1": (200, [{"id": "r1", "besluitVerplicht": True}, {"id": "r2"}]),
            "GET /rest/planitems/zaak/z1/userEventListenerPlanItems": (
                200,
                [{"id": "p1", "userEventListenerActie": "ZAAK_AFHANDELEN"}],
            ),
            "POST /rest/planitems/doUserEventListenerPlanItem": (204, None),
            "PATCH /rest/zaken/zaak/z1/afsluiten": (200, {"isOpen": False}),
        }
    )
    http, zaak = requests.Session(), {"uuid": "z1", "zaaktype": {"uuid": "zt1"}}
    zac.afhandelen(http, ZAC, zaak)
    assert json.loads(sent[-1].body)["resultaattypeUuid"] == "r2"
    zac.afsluiten(http, ZAC, zaak)
    assert json.loads(sent[-1].body) == {"reden": "podiumd-tests", "resultaattypeUuid": "r2"}
    zac.afhandelen(http, ZAC, zaak, "r1", restMailGegevens={"onderwerp": "x"})
    assert json.loads(sent[-1].body)["resultaattypeUuid"] == "r1"
    assert json.loads(sent[-1].body)["restMailGegevens"] == {"onderwerp": "x"}
    zac.afsluiten(http, ZAC, zaak, "r1")
    assert json.loads(sent[-1].body)["resultaattypeUuid"] == "r1"


def test_afbreken_takes_a_zaakbeeindigreden_and_brondatum_zetten_a_zoned_date(fake_http):
    sent = fake_http(
        {
            "PATCH /rest/zaken/zaak/z1/afbreken": (200, {}),
            "POST /rest/planitems/doUserEventListenerPlanItem": (204, None),
        }
    )
    http, zaak = requests.Session(), {"uuid": "z1"}
    zac.afbreken(http, ZAC, zaak)
    assert json.loads(sent[-1].body) == {"zaakbeeindigRedenId": zac.NIET_ONTVANKELIJK}
    zac.afbreken(http, ZAC, zaak, "7")
    assert json.loads(sent[-1].body) == {"zaakbeeindigRedenId": "7"}
    zac.brondatum_zetten(http, ZAC, zaak, "2026-11-20")
    assert json.loads(sent[-1].body) == {
        "zaakUuid": "z1",
        "actie": "BRONDATUM_ZETTEN",
        "brondatum": "2026-11-20T00:00:00Z",
    }


@pytest.mark.parametrize(("status", "found"), [(200, {"onderwerp": "Afgehandeld"}), (204, None)])
def test_zaak_mailtemplate_is_none_without_one(fake_http, status, found):
    fake_http({"GET /rest/mailtemplates/ZAAK_AFGEHANDELD/z1": (status, found)})
    assert zac.zaak_mailtemplate(requests.Session(), ZAC, {"uuid": "z1"}, "ZAAK_AFGEHANDELD") == found


@pytest.mark.parametrize(
    ("zaak", "methods"),
    [
        ({"isProcesGestuurd": True, "isOpen": True, "rechten": {"afbreken": True}}, ["GET", "PATCH"]),
        ({"isProcesGestuurd": False, "isOpen": True, "rechten": {"afbreken": True}}, ["GET"]),
        ({"isProcesGestuurd": True, "isOpen": True, "rechten": {"afbreken": False}}, ["GET"]),
        ({"isProcesGestuurd": True, "isOpen": True, "rechten": {"afbreken": True}, "isHeropend": True}, ["GET"]),
        ({"isProcesGestuurd": True, "isOpen": False, "rechten": {"afbreken": True}}, ["GET"]),
    ],
)
def test_end_process_aborts_only_a_zaak_with_a_process_that_zac_lets_abort(fake_http, zaak, methods):
    sent = fake_http(
        {"GET /rest/zaken/zaak/z1": (200, {"uuid": "z1", **zaak}), "PATCH /rest/zaken/zaak/z1/afbreken": (200, {})}
    )
    zac.end_process(requests.Session(), ZAC, "z1")
    assert [request.method for request in sent] == methods


@pytest.mark.parametrize(
    ("answer", "is_open"),
    [((200, {"status": "TOEGEKEND"}), True), ((200, {"status": "AFGEROND"}), False), ((404, {}), False)],
)
def test_is_task_open_is_a_read_task_not_afgerond(fake_http, answer, is_open):
    fake_http({"GET /rest/taken/t1": answer})
    assert zac_taken.is_task_open(requests.Session(), ZAC, "t1") is is_open


def test_clean_up_zaak_ends_the_process_before_it_deletes_the_zaak(fake_http):
    zaak = {"uuid": "z1", "isOpen": True, "isProcesGestuurd": True, "rechten": {"afbreken": True}}
    sent = fake_http(
        {
            "GET /rest/zaken/zaak/z1": (200, zaak),
            "PATCH /rest/zaken/zaak/z1/afbreken": (200, {}),
            "GET /zaken/api/v1/zaakinformatieobjecten": (200, []),
            "DELETE /zaken/api/v1/zaken/z1": (204, None),
        }
    )
    registry = ResourceRegistry("ptest-abc")
    openzaak = ApiClient(requests.Session(), "https://oz.test", {})
    zac.clean_up_zaak(requests.Session(), ZAC, openzaak, registry, {"uuid": "z1", "identificatie": "ZAAK-1"})
    assert registry.cleanup() == []
    assert [f"{request.method} {request.url}" for request in sent] == [
        f"GET {ZAC}/rest/zaken/zaak/z1",
        f"PATCH {ZAC}/rest/zaken/zaak/z1/afbreken",
        "GET https://oz.test/zaken/api/v1/zaakinformatieobjecten?zaak=https%3A%2F%2Foz.test%2Fzaken%2Fapi%2Fv1%2Fzaken%2Fz1",
        "DELETE https://oz.test/zaken/api/v1/zaken/z1",
    ]


def test_wijzig_zaak_sends_the_fields_with_omschrijving_zaaktype_and_reden(fake_http):
    sent = fake_http({"PATCH /rest/zaken/zaak/z1": (200, {})})
    zaak = {"uuid": "z1", "omschrijving": "o", "zaaktype": {"uuid": "zt1"}}
    zac.wijzig_zaak(requests.Session(), ZAC, zaak, uiterlijkeEinddatumAfdoening="2026-12-01")
    assert json.loads(sent[-1].body) == {
        "zaak": {"omschrijving": "o", "zaaktype": {"uuid": "zt1"}, "uiterlijkeEinddatumAfdoening": "2026-12-01"},
        "reden": "podiumd-tests",
    }
    assert sent[-1].timeout == zac.WIJZIG_TIMEOUT


def test_verdelen_and_vrijgeven_send_the_selection(fake_http):
    sent = fake_http({"PUT /rest/zaken/lijst/verdelen": (204, None), "PUT /rest/zaken/lijst/vrijgeven": (204, None)})
    http = requests.Session()
    zac.verdelen(http, ZAC, ["z1"], "g1", None)
    assert json.loads(sent[-1].body) == {
        "uuids": ["z1"],
        "groepId": "g1",
        "behandelaarGebruikersnaam": None,
        "reden": "podiumd-tests",
    }
    zac.vrijgeven(http, ZAC, ["z1"])
    assert json.loads(sent[-1].body) == {"uuids": ["z1"], "reden": "podiumd-tests"}


def test_taken_verdelen_and_vrijgeven_send_the_selected_taken(fake_http):
    sent = fake_http({"PUT /rest/taken/lijst/verdelen": (204, None), "PUT /rest/taken/lijst/vrijgeven": (204, None)})
    http = requests.Session()
    taak = {"id": "t1", "zaakUuid": "z1", "naam": "Intake"}
    selected = [{"taakId": "t1", "zaakUuid": "z1"}]
    zac_taken.verdelen_taken(http, ZAC, [taak], "g1", None)
    assert json.loads(sent[-1].body) == {
        "taken": selected,
        "groepId": "g1",
        "behandelaarGebruikersnaam": None,
        "reden": "podiumd-tests",
    }
    zac_taken.vrijgeven_taken(http, ZAC, [taak])
    assert json.loads(sent[-1].body) == {"taken": selected, "reden": "podiumd-tests"}


def test_toekennen_mij_sends_the_zaak_or_taak(fake_http):
    sent = fake_http(
        {"PUT /rest/zaken/lijst/toekennen/mij": (200, {}), "PATCH /rest/taken/lijst/toekennen/mij": (200, {})}
    )
    http = requests.Session()
    zac.toekennen_mij(http, ZAC, {"uuid": "z1"}, "g1")
    assert json.loads(sent[-1].body) == {"zaakUUID": "z1", "groepId": "g1", "reden": "podiumd-tests"}
    zac.taak_toekennen_mij(http, ZAC, {"id": "t1", "zaakUuid": "z1"})
    assert json.loads(sent[-1].body)["taakId"] == "t1"


def test_assignment_is_group_and_behandelaar():
    assert zac.assignment({"groep": {"id": "g1"}, "behandelaar": {"id": "u1"}}) == ("g1", "u1")
    assert zac.assignment({"groep": {"id": "g1"}, "behandelaar": None}) == ("g1", None)


def test_listed_assignment_is_group_and_behandelaar_of_a_search_result():
    assert zac.listed_assignment({"groepId": "g1", "behandelaarGebruikersnaam": "u1"}) == ("g1", "u1")
    assert zac.listed_assignment({"groepId": "g1"}) == ("g1", None)


def test_configure_zaaktype_saves_the_cmmn_model_groep_resultaattype_and_user_events(fake_http):
    model = {
        "naam": "Generiek",
        "userEventListenerDefinitions": [{"id": "INTAKE_AFRONDEN", "naam": "Intake afronden", "type": "X"}],
    }
    sent = fake_http(
        {
            "GET /rest/zaakafhandelparameters/case-definitions/generiek-zaakafhandelmodel": (200, model),
            "GET /rest/zaakafhandelparameters/resultaattypes/zt1": (200, [{"id": "r1"}, {"id": "r2"}]),
            "GET /rest/zaakafhandelparameters/zt1": (200, {"id": None, "zaaktype": {"uuid": "zt1"}}),
            "PUT /rest/zaakafhandelparameters": (200, {"id": 7, "valide": True}),
        }
    )
    saved = zac.configure_zaaktype(requests.Session(), ZAC, "zt1", "g1", intakeMail="NIET_BESCHIKBAAR")
    assert saved == {"id": 7, "valide": True}
    assert json.loads(sent[-1].body) == {
        "id": None,
        "zaaktype": {"uuid": "zt1"},
        "caseDefinition": {"key": "generiek-zaakafhandelmodel", "naam": "Generiek"},
        "defaultGroepId": "g1",
        "zaakNietOntvankelijkResultaattype": {"id": "r1"},
        "userEventListenerParameters": [{"id": "INTAKE_AFRONDEN", "naam": "Intake afronden"}],
        "intakeMail": "NIET_BESCHIKBAAR",
    }


def test_put_zaakafhandelparameters_gives_zacs_answer(fake_http):
    fake_http({"PUT /rest/zaakafhandelparameters": (400, {"message": "bezet"})})
    assert zac.put_zaakafhandelparameters(requests.Session(), ZAC, {}).status_code == 400


def test_copied_zaakafhandelparameters_waits_for_their_id(monkeypatch):
    monkeypatch.setattr(zac, "wait_until", functools.partial(wait_until, clock=Clock(sleep=lambda _seconds: None)))
    answers = iter([{"id": None}, {"id": 3}])
    monkeypatch.setattr(zac, "read_zaakafhandelparameters", lambda *_args: next(answers))
    assert zac.copied_zaakafhandelparameters(requests.Session(), ZAC, "zt2") == {"id": 3}


def test_comparable_leaves_out_what_differs_between_versions():
    resultaattype = {"id": "r1", "naam": "Afgehandeld", "naamGeneriek": "Afgebroken"}
    first = {
        "id": 1,
        "creatiedatum": "x",
        "zaaktype": {"uuid": "zt1"},
        "zaakNietOntvankelijkResultaattype": resultaattype,
        "zaakAfzenders": [{"id": 1, "mail": "B"}, {"id": 2, "mail": "A"}],
    }
    second = {
        **first,
        "id": 2,
        "zaaktype": {"uuid": "zt2"},
        "zaakNietOntvankelijkResultaattype": {**resultaattype, "id": "r9"},
        "zaakAfzenders": [{"id": 5, "mail": "A"}, {"id": 6, "mail": "B"}],
    }
    assert zac.comparable(first) == zac.comparable(second)
    assert zac.comparable({**second, "defaultGroepId": "g2"}) != zac.comparable(first)


def test_behandelaar_groups_are_zacs_groups_for_the_zaaktype(fake_http):
    fake_http({"GET /rest/identity/zaaktype/zt/behandelaar-groups": (200, [{"id": "g1"}, {"id": "g2"}])})
    assert zac.behandelaar_groups(requests.Session(), ZAC, "zt") == {"g1", "g2"}


def test_behandelaar_groups_of_several_zaaktypen_are_zacs_common_groups(fake_http):
    sent = fake_http({"POST /rest/identity/behandelaar-groups": (200, [{"id": "g1", "naam": "G1"}])})
    assert zac.behandelaar_groups(requests.Session(), ZAC, "zt1", "zt2") == {"g1"}
    assert json.loads(sent[-1].body) == {"zaaktypeDescriptions": ["zt1", "zt2"]}


def test_afronden_intake_and_afbreken(fake_http, monkeypatch):
    events = []
    monkeypatch.setattr(zac, "user_event", lambda *args, **fields: events.append((args[3], fields)) or _ok())
    sent = fake_http({"PATCH /rest/zaken/zaak/z1/afbreken": (204, None)})
    zaak = {"uuid": "z1"}
    zac.afronden_intake(requests.Session(), ZAC, zaak)
    assert events == [("INTAKE_AFRONDEN", {"zaakOntvankelijk": True})]
    assert zac.afbreken(requests.Session(), ZAC, zaak).status_code == 204
    assert json.loads(sent[-1].body) == {"zaakbeeindigRedenId": "ZAAK_NIET_ONTVANKELIJK"}


def _ok():
    response = requests.Response()
    response.status_code = 204
    return response


def test_rights_of_gives_a_role_the_rights_of_the_roles_before_it():
    least = {"lezen": "raadpleger", "wijzigen": "recordmanager", "versturenEmail": None}
    assert zac.rights_of("raadpleger", least) == {"lezen": True, "wijzigen": False, "versturenEmail": False}
    assert zac.rights_of("beheerder", least) == {"lezen": True, "wijzigen": True, "versturenEmail": False}


def test_productaanvraag_zaken_are_all_zaken_with_the_kenmerk(fake_http):
    zaken = [{"url": "z/1", "toelichting": "kenmerk OF-42"}, {"url": "z/2"}, {"url": "z/3", "toelichting": "OF-42"}]
    fake_http({"GET /zaken/api/v1/zaken": (200, zaken)})
    openzaak = ApiClient(requests.Session(), "https://oz.test", {})
    assert [zaak["url"] for zaak in zac.productaanvraag_zaken(openzaak, "OF-42")] == ["z/1", "z/3"]


def test_inbox_productaanvragen_of_a_type_and_their_cleanup(fake_http):
    found = {"resultaten": [{"id": 7, "type": "t"}], "totaal": 1}
    sent = fake_http(
        {"PUT /rest/inbox-productaanvragen": (200, found), "DELETE /rest/inbox-productaanvragen/7": (204, None)}
    )
    http, registry = requests.Session(), ResourceRegistry("ptest-abc")
    assert zac.inbox_productaanvragen(http, ZAC, "t") == found["resultaten"]
    assert json.loads(sent[0].body)["type"] == "t"
    zac.clean_up_inbox_entries(http, ZAC, registry, "t")
    assert registry.cleanup() == []
    assert (sent[-1].method, sent[-1].url) == ("DELETE", f"{ZAC}/rest/inbox-productaanvragen/7")


def test_inbox_productaanvraag_is_the_first_entry_of_the_type(fake_http):
    fake_http({"PUT /rest/inbox-productaanvragen": (200, {"resultaten": [{"id": 7}, {"id": 8}], "totaal": 2})})
    assert zac.inbox_productaanvraag(requests.Session(), ZAC, "t") == {"id": 7}


def test_zaak_with_contactgegevens_is_the_zaak_once_zac_shows_them(fake_http):
    shown = {"uuid": "u-1", "zaakSpecificContactDetails": {"emailAddress": "a@example.invalid"}}
    fake_http({"GET /rest/zaken/zaak/u-1": (200, shown)})
    assert zac.zaak_with_contactgegevens(requests.Session(), ZAC, "u-1") == shown


def test_inbox_productaanvragen_page_sends_the_type_the_page_and_its_size(fake_http):
    page = {"resultaten": [{"id": 7}], "totaal": 2.0}
    sent = fake_http({"PUT /rest/inbox-productaanvragen": (200, page)})
    assert zac.inbox_productaanvragen_page(requests.Session(), ZAC, "t", 1, 1) == page
    assert json.loads(sent[-1].body) == {"type": "t", "page": 1, "maxResults": 1}


def test_deliver_notificatie_posts_it_in_the_zac_pod_this_many_times(env_factory, fake_runner):
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "zac"}}]}))
    fake_runner.answers["exec deploy/zac"] = (0, "204\n204\n")
    assert zac.deliver_notificatie(env_factory(), {"actie": "create"}, 2) == [204, 204]
    argv = fake_runner.calls[-1]
    assert "for i in 0 1;" in argv[-3]
    assert "$OPEN_NOTIFICATIONS_API_SECRET_KEY" in argv[-3]
    assert json.loads(argv[-1]) == {"actie": "create"}


def test_forget_zaak_at_cleanup_delivers_its_destroy_notificatie(env_factory, monkeypatch):
    delivered = []
    monkeypatch.setattr(zac, "deliver_notificatie", lambda _env, message, times: delivered.append((message, times)))
    env = env_factory()
    registry = ResourceRegistry("run1")
    zac.forget_zaak_at_cleanup(env, registry, {"uuid": "z1", "identificatie": "ZAAK-1"})
    assert delivered == []
    registry.cleanup()
    message, times = delivered[0]
    url = f"{env.profile.urls['openzaak']}/zaken/api/v1/zaken/z1"
    assert (message["resource"], message["resourceUrl"], message["actie"], times) == ("zaak", url, "destroy", 1)


def test_taak_listed_searches_by_zaak_identificatie_and_matches_the_id(fake_http):
    sent = fake_http({"PUT /rest/zoeken/list": (200, {"resultaten": [{"id": "t1"}]})})
    taak = {"id": "t1", "zaakIdentificatie": "ZAAK-1"}
    assert zac.is_taak_listed(requests.Session(), ZAC, taak, alleenMijnTaken=True)
    assert not zac.is_taak_listed(requests.Session(), ZAC, {**taak, "id": "t2"})
    body = json.loads(sent[0].body)
    assert (body["type"], body["zoeken"], body["alleenMijnTaken"]) == ("TAAK", {"TAAK_ZAAK_ID": "ZAAK-1"}, True)


def test_wait_for_indicatie_needs_the_indicatie_on_the_open_zaak(fake_http):
    found = {"resultaten": [{"id": "z1", "indicaties": ["OPSCHORTING"]}]}
    sent = fake_http({"PUT /rest/zoeken/list": (200, found)})
    zaak = {"uuid": "z1", "identificatie": "ZAAK-1"}
    zac.wait_for_indicatie(requests.Session(), ZAC, zaak, "OPSCHORTING")
    assert json.loads(sent[0].body)["alleenOpenstaandeZaken"] is True
    assert zac.zaak_zoekresultaat(requests.Session(), ZAC, {**zaak, "uuid": "z2"}) is None


def test_toekennen_and_toekennen_taak_send_group_and_behandelaar(fake_http):
    sent = fake_http({"PATCH /rest/zaken/toekennen": (200, {}), "PATCH /rest/taken/toekennen": (204, None)})
    http = requests.Session()
    zac.toekennen(http, ZAC, {"uuid": "z1"}, "g1", "u1")
    assert json.loads(sent[-1].body) == {
        "zaakUUID": "z1",
        "groepId": "g1",
        "behandelaarGebruikersnaam": "u1",
        "reden": "podiumd-tests",
    }
    zac_taken.toekennen_taak(http, ZAC, {"id": "t1", "zaakUuid": "z1"}, "g1", "u1")
    assert json.loads(sent[-1].body) == {
        "taakId": "t1",
        "zaakUuid": "z1",
        "groepId": "g1",
        "behandelaarId": "u1",
        "reden": "podiumd-tests",
    }


def test_wijzig_taak_saves_the_read_taak_with_the_fields(fake_http):
    sent = fake_http(
        {"GET /rest/taken/t1": (200, {"id": "t1", "toelichting": "x"}), "PUT /rest/taken/taakdata": (200, {})}
    )
    zac_taken.wijzig_taak(requests.Session(), ZAC, "t1", fataledatum="2026-11-10")
    assert json.loads(sent[-1].body) == {"id": "t1", "toelichting": "x", "fataledatum": "2026-11-10"}


def test_opschorten_verlengen_and_heropenen_send_days_dates_and_reden(fake_http):
    sent = fake_http(
        {
            "PATCH /rest/zaken/zaak/z1/suspend": (200, {}),
            "PATCH /rest/zaken/zaak/z1/verlenging": (200, {}),
            "PATCH /rest/zaken/zaak/z1/heropenen": (200, {}),
            "PATCH /rest/zaken/zaak/z1/resume": (200, {}),
        }
    )
    http = requests.Session()
    zaak = {"uuid": "z1", "einddatumGepland": "2026-01-10", "uiterlijkeEinddatumAfdoening": "2026-01-31"}
    zac.opschorten(http, ZAC, zaak, 3, "op")
    assert json.loads(sent[-1].body) == {"reason": "op", "numberOfDays": 3}
    zac.verlengen(http, ZAC, zaak, 2)
    assert json.loads(sent[-1].body) == {
        "redenVerlenging": "podiumd-tests",
        "duurDagen": 2,
        "takenVerlengen": False,
        "einddatumGepland": "2026-01-12",
        "uiterlijkeEinddatumAfdoening": "2026-02-02",
    }
    zac.verlengen(http, ZAC, zaak, 2, takenVerlengen=True)
    assert json.loads(sent[-1].body)["takenVerlengen"] is True
    zac.verlengen(http, ZAC, {"uuid": "z1", "uiterlijkeEinddatumAfdoening": "2026-01-31"}, 2, None)
    assert "einddatumGepland" not in json.loads(sent[-1].body)
    assert zac.moved_dates(zaak, 0) == {"einddatumGepland": "2026-01-10", "uiterlijkeEinddatumAfdoening": "2026-01-31"}
    assert json.loads(sent[-1].body)["redenVerlenging"] is None
    zac.opschorten(http, ZAC, zaak, 3, None)
    assert json.loads(sent[-1].body) == {"reason": None, "numberOfDays": 3}
    zac.heropenen(http, ZAC, zaak)
    assert json.loads(sent[-1].body) == {"reden": "podiumd-tests"}
    zac.hervatten(http, ZAC, zaak, "")
    assert json.loads(sent[-1].body) == {"reason": ""}


def test_groups_members_and_taak_are_read_from_zac(fake_http):
    fake_http(
        {
            "GET /rest/identity/groups": (200, [{"id": "g1", "naam": "G", "active": True}]),
            "GET /rest/identity/groups/g1/users": (200, [{"id": "u1", "naam": "U"}]),
            "GET /rest/taken/t1": (200, {"id": "t1"}),
        }
    )
    http = requests.Session()
    assert zac.active_groups(http, ZAC) == {"g1"}
    assert zac.group_members(http, ZAC, "g1") == {"u1"}
    assert zac_taken.read_taak(http, ZAC, "t1") == {"id": "t1"}


def test_csv_export_reads_the_rows_by_column_and_skips_repeated_header_names(monkeypatch, response_factory):
    text = '"identificatie";"omschrijving";"identificatie"\n"ZAAK-1";"een"\n"ZAAK-2";"twee"\n'
    sent = []

    def post(_session, url, json=None, **_kwargs):
        sent.append((url, json))
        return response_factory(body=text.encode())

    monkeypatch.setattr(requests.Session, "post", post)
    rows = zac.csv_export(requests.Session(), ZAC, type="ZAAK", rows=2)
    assert rows == [
        {"identificatie": "ZAAK-1", "omschrijving": "een"},
        {"identificatie": "ZAAK-2", "omschrijving": "twee"},
    ]
    assert sent == [(f"{ZAC}/rest/csv/export", {"page": 0, "rows": 2, "type": "ZAAK"})]


def test_zoekopdracht_is_saved_listed_and_deleted_at_cleanup(fake_http):
    saved = {"id": 7, "naam": "n", "lijstID": "WERKVOORRAAD_ZAKEN", "json": "{}"}
    sent = fake_http(
        {
            "POST /rest/gebruikersvoorkeuren/zoekopdracht": (200, saved),
            "GET /rest/gebruikersvoorkeuren/zoekopdracht/WERKVOORRAAD_ZAKEN": (200, [saved]),
            "DELETE /rest/gebruikersvoorkeuren/zoekopdracht/7": (204, None),
        }
    )
    http, registry = requests.Session(), ResourceRegistry("run")
    assert zac.save_zoekopdracht(http, ZAC, registry, "WERKVOORRAAD_ZAKEN", {"filters": {}}) == saved
    body = json.loads(sent[-1].body)
    assert (body["lijstID"], body["json"]) == ("WERKVOORRAAD_ZAKEN", '{"filters": {}}')
    assert body["naam"].startswith("run-zoekopdracht-")
    assert zac.zoekopdrachten(http, ZAC, "WERKVOORRAAD_ZAKEN") == [saved]
    assert registry.cleanup() == []
    assert sent[-1].method == "DELETE"


def test_document_listed_searches_by_titel_and_matches_the_uuid(fake_http):
    sent = fake_http({"PUT /rest/zoeken/list": (200, {"resultaten": [{"id": "d1"}]})})
    document = {"uuid": "d1", "titel": "brief"}
    assert zac.is_document_listed(requests.Session(), ZAC, document)
    assert not zac.is_document_listed(requests.Session(), ZAC, {**document, "uuid": "d2"})
    body = json.loads(sent[0].body)
    assert (body["type"], body["zoeken"]) == ("DOCUMENT", {"DOCUMENT_TITEL": "brief"})


def test_bag_object_is_linked_and_unlinked_with_a_reden_and_the_locatie_set(fake_http):
    sent = fake_http(
        {
            "POST /rest/bag": (204, None),
            "DELETE /rest/bag": (204, None),
            "PATCH /rest/zaken/z1/zaaklocatie": (200, {}),
        }
    )
    http, zaak = requests.Session(), {"uuid": "z1"}
    zac.koppel_bag_object(http, ZAC, zaak, {"identificatie": "a1"})
    assert json.loads(sent[-1].body) == {"zaakUuid": "z1", "zaakobject": {"identificatie": "a1"}}
    zac.ontkoppel_bag_object(http, ZAC, zaak, {"uuid": "o1"}, "weg")
    assert json.loads(sent[-1].body) == {"uuid": "o1", "zaakUuid": "z1", "redenWijzigen": "weg"}
    zac.zaaklocatie(http, ZAC, zaak, None, "weg")
    assert json.loads(sent[-1].body) == {"geometrie": None, "reden": "weg"}


def test_zoned_brondatum_is_the_day_at_midnight_utc():
    assert zac.zoned_brondatum("2026-11-12") == "2026-11-12T00:00:00Z"
