"""Unit tests for the productaanvraag form, its zaaktype in ZAC and its cleanup."""

import json

import pytest
import requests

from podiumd_tests import zac_productaanvraag
from podiumd_tests.clients.api import ApiClient
from podiumd_tests.json_data import section
from podiumd_tests.openformulieren import productaanvraag_registration
from podiumd_tests.seed.catalogi import ZaaktypeTypes
from podiumd_tests.seed.objecten import forget_productaanvraag
from podiumd_tests.seed.registry import ResourceRegistry

API = "https://api.example.test"


@pytest.mark.parametrize("auth_initiator", [True, False])
def test_registration_template_names_the_type_and_the_logged_in_initiator(profile_factory, env_factory, auth_initiator):
    env = env_factory(profile_factory(urls={"objecten": API}))
    registration = productaanvraag_registration(
        env, f"{API}/objecttypes/ot1/", "ptest-type", auth_initiator=auth_initiator
    )
    options = section(registration, "options")
    assert (registration["objects_api"], options["objecttype"]) == (f"{API}/api/v2/", "ot1")
    rendered = str(options["content_json"]).replace("{% json_summary %}", "{}")
    content = json.loads(rendered)
    assert content["type"] == "ptest-type"
    wanted = (
        [{"inpBsn": "{{ variables.auth_bsn }}", "rolOmschrijvingGeneriek": "initiator"}] if auth_initiator else None
    )
    assert content.get("betrokkenen") == wanted


def test_forget_productaanvraag_deletes_the_objects_of_the_kenmerk(fake_http):
    found = {"results": [{"url": f"{API}/objects/o1"}], "next": None}
    sent = fake_http({"GET /objects": (200, found), "DELETE /objects/o1": (204, None)})
    registry = ResourceRegistry("ptest-x")
    forget_productaanvraag(ApiClient(requests.Session(), API, {}), registry, "OF-1")
    registry.cleanup()
    assert [(s.method, s.url.split("?")[0]) for s in sent] == [
        ("GET", f"{API}/objects"),
        ("DELETE", f"{API}/objects/o1"),
    ]


def test_productaanvraag_zaaktype_sets_the_aanvraagtype_and_the_koppelingen(monkeypatch, env_factory, profile_factory):
    saved = []
    monkeypatch.setattr(zac_productaanvraag, "make_zac_zaaktype", lambda *_args, **_kwargs: {"id": 1})
    monkeypatch.setattr(zac_productaanvraag, "zac_as_admin", lambda _env: "zac")
    monkeypatch.setattr(zac_productaanvraag, "save_zaakafhandelparameters", lambda *args: saved.append(args))
    env = env_factory(profile_factory(urls={"zac": "https://zac.example.test"}))
    types = ZaaktypeTypes()
    client = ApiClient(requests.Session(), API, {})
    zac = zac_productaanvraag.productaanvraag_zaaktype(
        env, client, ResourceRegistry("ptest-x"), {}, aanvraagtype="ptest-a", types=types
    )
    assert zac == "zac"
    assert saved[0][2] == {
        "id": 1,
        "productaanvraagtype": "ptest-a",
        "betrokkeneKoppelingen": {"brpKoppelen": True, "kvkKoppelen": True},
    }


def stub_form(monkeypatch):
    monkeypatch.setattr(zac_productaanvraag, "make_form", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(zac_productaanvraag, "logged_in_submission", lambda *_args: ("http", {"id": "s"}, {}))
    result = {"publicReference": "OF-1"}
    monkeypatch.setattr(zac_productaanvraag, "complete_submission", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(zac_productaanvraag, "forget_productaanvraag", lambda *_args: None)


def digid_aanvraag(env):
    objecten = ApiClient(requests.Session(), API, {})
    return zac_productaanvraag.submit_digid_aanvraag(
        env, objecten, ResourceRegistry("ptest-x"), objecttype=f"{API}/ot/1", aanvraagtype="t", bsn="1"
    )


def test_digid_aanvraag_returns_the_registered_data(monkeypatch, env_factory, profile_factory, fake_http):
    stub_form(monkeypatch)
    found = {"results": [{"record": {"data": {"bron": {"kenmerk": "OF-1"}}}}], "next": None}
    fake_http({"GET /objects": (200, found)})
    assert digid_aanvraag(env_factory(profile_factory(urls={"objecten": API}))) == {"bron": {"kenmerk": "OF-1"}}


def test_digid_aanvraag_without_its_object_fails(monkeypatch, env_factory, profile_factory, fake_http):
    stub_form(monkeypatch)
    fake_http({"GET /objects": (200, {"results": [], "next": None})})
    with pytest.raises(AssertionError, match="0 productaanvraag objects"):
        digid_aanvraag(env_factory(profile_factory(urls={"objecten": API})))
