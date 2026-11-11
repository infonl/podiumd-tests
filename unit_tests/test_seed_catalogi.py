"""Unit tests for the throwaway catalogus types and their removal."""

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

    monkeypatch.setattr(catalogi, "run_snippet", run)
    monkeypatch.setattr("podiumd_tests.seed.registry.run_snippet", run)
    return ran


def env():
    return SimpleNamespace(kube=object(), deployment_for=lambda component: f"{component}-deploy")


def test_removal_refuses_a_name_without_run_tag(snippets):
    with pytest.raises(ValueError, match="no run tag"):
        catalogi.remove_catalogus_type(env(), "ptest-bootstrap-klacht")  # pyright: ignore[reportArgumentType]
    assert snippets == []


def test_list_remove_and_forget_run_the_snippet(snippets):
    assert catalogi.tagged_catalogus_types(env()) == [TAGGED]  # pyright: ignore[reportArgumentType]
    catalogi.remove_catalogus_type(env(), TAGGED)  # pyright: ignore[reportArgumentType]
    registry = ResourceRegistry("run1")
    catalogi.forget_catalogus_type(env(), registry, TAGGED)  # pyright: ignore[reportArgumentType]
    registry.cleanup()
    assert [(d, p["action"], p.get("name")) for d, _, p in snippets] == [
        ("openzaak-deploy", "list", None),
        ("openzaak-deploy", "delete", TAGGED),
        ("openzaak-deploy", "delete", TAGGED),
    ]


@pytest.mark.parametrize(
    ("types", "statustypen", "roltypen"),
    [((), 2, 1), ((catalogi.ZaaktypeTypes(("a", "b", "c"), (("i", "initiator"), ("b", "behandelaar"))),), 3, 2)],
)
def test_publishable_zaaktype_copies_the_templates_resultaattype(snippets, fake_http, types, statustypen, roltypen):
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
        }
    )
    client = ApiClient(requests.Session(), API, {})
    registry = ResourceRegistry("run1")
    template = {"url": "tpl", "catalogus": "cat", "selectielijstProcestype": "proc"}
    zaaktype = catalogi.make_publishable_zaaktype(env(), client, registry, template, *types)  # pyright: ignore[reportArgumentType]
    assert catalogi.publish(client, zaaktype) == new
    posted = [s.url.removeprefix(API) for s in sent if s.method == "POST"]
    assert posted.count("/catalogi/api/v1/statustypen") == statustypen
    assert posted.count("/catalogi/api/v1/roltypen") == roltypen
    registry.cleanup()
    assert [p["name"] for _, _, p in snippets] == [TAGGED]


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
