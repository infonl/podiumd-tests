"""Unit tests for the ZAC REST helpers."""

import functools
import json

import pytest
import requests

from podiumd_tests import zac
from podiumd_tests.clients.api import ApiClient
from podiumd_tests.oidc import LOGIN_PATHS
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
    assert zac.activate_human_tasks(requests.Session(), ZAC, "zt1", GOEDKEUREN={"doorlooptijd": 10}) == {"id": 7}
    saved = json.loads(sent[-1].body)
    assert saved["id"] == 7
    assert saved["humanTaskParameters"] == [
        {"actief": True, "planItemDefinition": {"id": "GOEDKEUREN"}, "doorlooptijd": 10},
        {"actief": True, "planItemDefinition": {"id": "ADVIES_INTERN"}, "referentieTabellen": [{"veld": "ADVIES"}]},
    ]


def test_start_human_task_waits_until_zac_offers_it_and_starts_it_without_a_mail(fake_http, monkeypatch):
    offers = iter([[], [{"id": "p9", "naam": "Goedkeuren"}]])
    monkeypatch.setattr(zac, "human_tasks_offered", lambda *_args: next(offers))
    monkeypatch.setattr(zac, "wait_until", functools.partial(wait_until, clock=Clock(sleep=lambda _s: None)))
    sent = fake_http({"POST /rest/planitems/doHumanTaskPlanItem": (204, None)})
    zaak = {"uuid": "z1", "identificatie": "ZAAK-1"}
    response = zac.start_human_task(requests.Session(), ZAC, zaak, "Goedkeuren", "g1", fataledatum="2026-12-01")
    assert response.status_code == 204
    assert json.loads(sent[-1].body) == {
        "planItemInstanceId": "p9",
        "groep": {"id": "g1", "naam": "g1"},
        "taakdata": {},
        "taakStuurGegevens": {"sendMail": False},
        "fataledatum": "2026-12-01",
    }


def test_human_tasks_and_user_events_offered_are_zacs_plan_items(fake_http):
    fake_http(
        {
            "GET /rest/planitems/zaak/z1/humanTaskPlanItems": (200, [{"naam": "Goedkeuren"}]),
            "GET /rest/planitems/zaak/z1/userEventListenerPlanItems": (200, [{"userEventListenerActie": "X"}]),
        }
    )
    http = requests.Session()
    assert zac.human_tasks_offered(http, ZAC, {"uuid": "z1"}) == [{"naam": "Goedkeuren"}]
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


def test_zaak_historie_lists_zacs_answer(fake_http):
    fake_http({"GET /rest/zaken/zaak/z1/historie": (200, [{"actie": "AANGEMAAKT"}])})
    assert zac.zaak_historie(requests.Session(), ZAC, {"uuid": "z1"}) == [{"actie": "AANGEMAAKT"}]


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


def test_wijzig_zaak_sends_the_fields_with_omschrijving_zaaktype_and_reden(fake_http):
    sent = fake_http({"PATCH /rest/zaken/zaak/z1": (200, {})})
    zaak = {"uuid": "z1", "omschrijving": "o", "zaaktype": {"uuid": "zt1"}}
    zac.wijzig_zaak(requests.Session(), ZAC, zaak, uiterlijkeEinddatumAfdoening="2026-12-01")
    assert json.loads(sent[-1].body) == {
        "zaak": {"omschrijving": "o", "zaaktype": {"uuid": "zt1"}, "uiterlijkeEinddatumAfdoening": "2026-12-01"},
        "reden": "podiumd-tests",
    }


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


def test_assignment_is_group_and_behandelaar():
    assert zac.assignment({"groep": {"id": "g1"}, "behandelaar": {"id": "u1"}}) == ("g1", "u1")
    assert zac.assignment({"groep": {"id": "g1"}, "behandelaar": None}) == ("g1", None)


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


def test_deliver_notificatie_posts_it_in_the_zac_pod_this_many_times(env_factory, fake_runner):
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "zac"}}]}))
    fake_runner.answers["exec deploy/zac"] = (0, "204\n204\n")
    assert zac.deliver_notificatie(env_factory(), {"actie": "create"}, 2) == [204, 204]
    argv = fake_runner.calls[-1]
    assert "for i in 0 1;" in argv[-3]
    assert "$OPEN_NOTIFICATIONS_API_SECRET_KEY" in argv[-3]
    assert json.loads(argv[-1]) == {"actie": "create"}
