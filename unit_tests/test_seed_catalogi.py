"""Unit tests for the throwaway catalogus types and their removal."""

import json

from types import SimpleNamespace

import pytest
import requests

from podiumd_tests.clients.api import ApiClient
from podiumd_tests.seed import catalogi
from podiumd_tests.seed.registry import ResourceRegistry

API = "https://api.example.test/v1"
TAGGED = "ptest-2611111200abcd-zaaktype-1"


@pytest.fixture(name="snippets")
def fixture_snippets(monkeypatch):
    """Record run_snippet calls; list answers one tagged name."""
    ran = []

    def run(_kube, deployment, name, params):
        ran.append((deployment, name, params))
        return [TAGGED] if params["action"] == "list" else {"deleted": params.get("name")}

    monkeypatch.setattr("podiumd_tests.seed.tagged_types.run_snippet", run)
    monkeypatch.setattr("podiumd_tests.seed.registry.run_snippet", run)
    return ran


def env(*, zac_writes=False):
    profile = SimpleNamespace(is_allowed=lambda setting: zac_writes and setting == catalogi.ZAC_CATALOGUS_WRITES)
    return SimpleNamespace(
        kube=object(),
        deployment_for=lambda component: f"{component}-deploy",
        profile=profile,
        variable=lambda component, name: f"{component}-{name}",
    )


def test_removal_refuses_a_name_without_run_tag(snippets):
    with pytest.raises(ValueError, match="no run tag"):
        catalogi.CATALOGUS_TYPES.remove(env(), "ptest-bootstrap-klacht")  # pyright: ignore[reportArgumentType]
    assert snippets == []


def test_list_remove_and_forget_run_the_snippet(snippets):
    assert catalogi.CATALOGUS_TYPES.tagged(env()) == [TAGGED]  # pyright: ignore[reportArgumentType]
    catalogi.CATALOGUS_TYPES.remove(env(), TAGGED)  # pyright: ignore[reportArgumentType]
    registry = ResourceRegistry("run1")
    catalogi.forget_catalogus_type(env(), registry, TAGGED)  # pyright: ignore[reportArgumentType]
    registry.cleanup()
    assert [(d, p["action"], p.get("name")) for d, _, p in snippets] == [
        ("openzaak-deploy", "list", None),
        ("openzaak-deploy", "delete", TAGGED),
        ("openzaak-deploy", "delete", TAGGED),
    ]
    assert {str(p["catalogi"]) for _, _, p in snippets} == {str([catalogi.CATALOGUS])}


def test_list_and_remove_cover_zacs_catalogus_where_the_profile_allows_writes(snippets):
    catalogi.CATALOGUS_TYPES.tagged(env(zac_writes=True))  # pyright: ignore[reportArgumentType]
    catalogi.CATALOGUS_TYPES.remove(env(zac_writes=True), TAGGED)  # pyright: ignore[reportArgumentType]
    zacs = {"domein": "zac-CATALOGUS_DOMEIN"}
    assert [p["catalogi"] for _, _, p in snippets] == [[catalogi.CATALOGUS, zacs], [catalogi.CATALOGUS, zacs]]


ALG = {"url": f"{API}/catalogi/api/v1/catalogussen/alg", "domein": "ALG", "rsin": "002220647"}


@pytest.mark.parametrize(
    ("types", "fields", "statustypen", "roltypen", "termijn"),
    [
        ((), {}, 2, 1, "P10Y"),
        ((catalogi.ZaaktypeTypes(("a", "b", "c"), (("i", "initiator"), ("b", "behandelaar"))),), {}, 3, 2, "P10Y"),
        ((catalogi.ZaaktypeTypes(archiefactietermijn=False),), {"catalogus": ALG["url"]}, 2, 1, None),
    ],
)
def test_publishable_zaaktype_copies_the_templates_resultaattype(
    snippets, fake_http, types, fields, statustypen, roltypen, termijn
):
    zaaktypen = "catalogi/api/v1/zaaktypen"
    resultaattype = {
        "resultaattypeomschrijving": "rto",
        "selectielijstklasse": "slk",
        "archiefnominatie": "vernietigen",
        "archiefactietermijn": "P10Y",
    }
    new = {"url": f"{API}/{zaaktypen}/new", "identificatie": TAGGED}
    sent = fake_http(
        {
            "GET /v1/catalogi/api/v1/resultaattypen": (200, {"results": [resultaattype], "next": None}),
            f"POST /v1/{zaaktypen}": (201, new),
            "POST /v1/catalogi/api/v1/statustypen": (201, {"url": "st"}),
            "POST /v1/catalogi/api/v1/roltypen": (201, {"url": "rt"}),
            "POST /v1/catalogi/api/v1/resultaattypen": (201, {"url": "rst"}),
            f"GET /v1/{zaaktypen}/new": (200, new),
            f"POST /v1/{zaaktypen}/new/publish": (200, {}),
            f"DELETE /v1/{zaaktypen}/new": (404, {}),
            "GET /v1/catalogi/api/v1/catalogussen/alg": (200, ALG),
        }
    )
    client = ApiClient(requests.Session(), API, {})
    registry = ResourceRegistry("run1")
    template = {"url": "tpl", "catalogus": "cat", "selectielijstProcestype": "proc"}
    zaaktype = catalogi.make_publishable_zaaktype(env(), client, registry, template, *types, **fields)  # pyright: ignore[reportArgumentType]
    assert catalogi.publish(client, zaaktype) == new
    posted = [s.url.removeprefix(API) for s in sent if s.method == "POST"]
    assert posted.count("/catalogi/api/v1/statustypen") == statustypen
    assert posted.count("/catalogi/api/v1/roltypen") == roltypen
    bodies = {s.url.removeprefix(API): json.loads(s.body) for s in sent if s.method == "POST" and s.body}
    assert bodies[f"/{zaaktypen}"]["catalogus"] == fields.get("catalogus", "cat")
    assert bodies["/catalogi/api/v1/resultaattypen"]["archiefactietermijn"] == termijn
    registry.cleanup()
    where = {"domein": ALG["domein"], "rsin": ALG["rsin"]} if fields else catalogi.CATALOGUS
    assert [(p["name"], p["catalogi"]) for _, _, p in snippets] == [(TAGGED, [where])]


def test_concept_iot_and_besluittype_are_tagged_and_forgotten(snippets, fake_http):
    fake_http(
        {
            "POST /v1/catalogi/api/v1/informatieobjecttypen": (201, {"url": "iot"}),
            "POST /v1/catalogi/api/v1/besluittypen": (201, {"url": "bt"}),
        }
    )
    client = ApiClient(requests.Session(), API, {})
    registry = ResourceRegistry("ptest-2611111200abcd")
    catalogi.make_concept_iot(env(), client, registry, "cat")  # pyright: ignore[reportArgumentType]
    catalogi.make_concept_besluittype(env(), client, registry, "cat")  # pyright: ignore[reportArgumentType]
    registry.cleanup()
    names = [str(p["name"]) for _, _, p in snippets]
    assert [name.rsplit("-", 1)[0] for name in names] == [
        "ptest-2611111200abcd-besluittype",
        "ptest-2611111200abcd-iot",
    ]
    assert len({name.rsplit("-", 1)[1] for name in names}) == 2  # each its own suffix


@pytest.mark.usefixtures("snippets")
def test_publishable_zaaktype_has_a_resultaattype_per_afleidingswijze_and_its_besluittypen_published(fake_http):
    zaaktypen = "catalogi/api/v1/zaaktypen"
    besluittype = f"{API}/catalogi/api/v1/besluittypen/b1"
    resultaattype = {
        "resultaattypeomschrijving": "rto",
        "selectielijstklasse": "slk",
        "archiefnominatie": "vernietigen",
        "archiefactietermijn": "P10Y",
    }
    klassen = [{"url": "nihil", "procestermijn": "nihil"}, {"url": "zonder", "procestermijn": ""}]
    new = {"url": f"{API}/{zaaktypen}/new", "identificatie": TAGGED}
    sent = fake_http(
        {
            "GET /v1/catalogi/api/v1/resultaattypen": (200, {"results": [resultaattype], "next": None}),
            "GET /api/v1/resultaten": (200, {"results": klassen}),
            f"POST /v1/{zaaktypen}": (201, new),
            "POST /v1/catalogi/api/v1/statustypen": (201, {"url": "st"}),
            "POST /v1/catalogi/api/v1/roltypen": (201, {"url": "rt"}),
            "POST /v1/catalogi/api/v1/eigenschappen": (201, {"url": "e"}),
            "POST /v1/catalogi/api/v1/resultaattypen": (201, {"url": "rst"}),
            f"GET /v1/{zaaktypen}/new": (200, new),
        }
    )
    client = ApiClient(requests.Session(), API, {})
    template = {"url": "tpl", "catalogus": "cat", "selectielijstProcestype": "https://sl.test/api/v1/procestypen/p1"}
    types = catalogi.ZaaktypeTypes(
        eigenschappen=("peildatum",), afleidingswijzen=("eigenschap", "termijn"), besluittypen=(besluittype,)
    )
    catalogi.make_publishable_zaaktype(env(), client, ResourceRegistry("run1"), template, types)  # pyright: ignore[reportArgumentType]
    created = [json.loads(s.body) for s in sent if s.method == "POST" and s.url.endswith("/resultaattypen")]
    assert [(r["omschrijving"], r["selectielijstklasse"]) for r in created] == [
        ("Afgehandeld", "slk"),
        ("eigenschap", "zonder"),
        ("termijn", "zonder"),
    ]
    procedures = [r["brondatumArchiefprocedure"] for r in created[1:]]
    assert [(p["datumkenmerk"], p["procestermijn"]) for p in procedures] == [("peildatum", None), ("", "P1Y")]
    concept = next(json.loads(s.body) for s in sent if s.method == "POST" and s.url.endswith(f"/{zaaktypen}"))
    assert concept["besluittypen"] == [besluittype]
