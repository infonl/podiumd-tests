"""Unit tests for the Open Zaak, Open Klant, Objecten and Open Notificaties factories."""

import base64
import json

from types import SimpleNamespace
from typing import Any
from typing import cast

import pytest
import requests

from podiumd_tests.clients.api import ApiClient
from podiumd_tests.environment import Environment
from podiumd_tests.seed import objecten as objecten_module
from podiumd_tests.seed import openklant
from podiumd_tests.seed import openzaak
from podiumd_tests.seed.objecten import clean_up_logboek
from podiumd_tests.seed.objecten import make_productaanvraag
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.opennotificaties import CALLBACK_AUTH
from podiumd_tests.seed.opennotificaties import make_abonnement
from podiumd_tests.seed.registry import ResourceRegistry

API = "https://api.example.test/v1"
ZAAK = f"{API}/zaken/api/v1/zaken/z1"


def api() -> ApiClient:
    return ApiClient(requests.Session(), API, {})


def calls(sent) -> list[tuple[str, str]]:
    """(method, path below API without query) of each sent request."""
    return [(s.method, s.url.split("?")[0].removeprefix(API)) for s in sent]


def body(sent) -> dict[str, Any]:
    return json.loads(sent.body)


def results(*items: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return 200, {"results": list(items), "next": None}


def created(path: str) -> dict[str, tuple[int, dict[str, Any]]]:
    """POST on path answers an object at path/new; DELETE of it 204."""
    return {
        f"POST /v1/{path}": (201, {"url": f"{API}/{path}/new", "uuid": "u-new"}),
        f"DELETE /v1/{path}/new": (204, {}),
    }


@pytest.mark.parametrize(
    ("factory", "path"),
    [
        (lambda c, r: openzaak.make_zaak(c, r, "zt"), "zaken/api/v1/zaken"),
        (lambda c, r: openzaak.make_rol(c, r, {"url": ZAAK}, "rt", inpBsn="1"), "zaken/api/v1/rollen"),
        (lambda c, r: openzaak.make_document(c, r, "iot"), "documenten/api/v1/enkelvoudiginformatieobjecten"),
        (lambda c, r: openzaak.link_document(c, r, {"url": ZAAK}, {"url": "d"}), "zaken/api/v1/zaakinformatieobjecten"),
        (lambda c, r: openzaak.make_besluit(c, r, "bt"), "besluiten/api/v1/besluiten"),
        (lambda c, r: openzaak.make_concept_zaaktype(c, r, "cat"), "catalogi/api/v1/zaaktypen"),
        (lambda c, r: openklant.make_partij(c, r), "partijen"),
        (openklant.make_organisatie, "partijen"),
        (lambda c, r: openklant.make_partij_identificator(c, r, {"uuid": "p"}, "bsn", "1"), "partij-identificatoren"),
        (lambda c, r: openklant.make_digitaal_adres(c, r, {"uuid": "p"}, "a@example.invalid"), "digitaleadressen"),
        (lambda c, r: openklant.make_klantcontact(c, r), "klantcontacten"),
        (lambda c, r: openklant.make_betrokkene(c, r, {"uuid": "k"}, None), "betrokkenen"),
        (lambda c, r: openklant.make_actor(c, r), "actoren"),
        (lambda c, r: openklant.make_internetaak(c, r, {"uuid": "k"}, [{"uuid": "a"}]), "internetaken"),
        (lambda c, r: openklant.make_onderwerpobject(c, r, {"uuid": "k"}, "z"), "onderwerpobjecten"),
        (lambda c, r: objecten_module.make_object(c, r, "ot", {"a": 1}), "objects"),
        (lambda c, r: make_abonnement(c, r, "https://cb.test/", "zaken", {}), "abonnement"),
    ],
)
def test_factories_post_and_delete_at_cleanup(fake_http, factory, path):
    sent = fake_http(created(path))
    registry = ResourceRegistry("run1")
    assert factory(api(), registry)["url"] == f"{API}/{path}/new"
    registry.cleanup()
    assert calls(sent) == [("POST", f"/{path}"), ("DELETE", f"/{path}/new")]


def test_tagged_fields_carry_the_run_tag(fake_http):
    sent = fake_http(created("partijen") | created("documenten/api/v1/enkelvoudiginformatieobjecten"))
    registry = ResourceRegistry("run1")
    openklant.make_organisatie(api(), registry)
    openzaak.make_document(api(), registry, "iot", inhoud="hallo")
    partij, document = body(sent[0]), body(sent[1])
    assert partij["soortPartij"] == "organisatie"
    assert partij["partijIdentificatie"] == {"naam": "run1-bv"}
    assert base64.b64decode(document["inhoud"]) == b"hallo"
    assert (document["titel"], document["bestandsomvang"]) == ("run1-document", 5)


@pytest.mark.parametrize(
    ("kind", "objecttype", "register"),
    [("bsn", "natuurlijk_persoon", "brp"), ("kvk_nummer", "niet_natuurlijk_persoon", "hr")],
)
def test_identificator_register_follows_its_kind(fake_http, kind, objecttype, register):
    sent = fake_http(created("partij-identificatoren"))
    openklant.make_partij_identificator(api(), ResourceRegistry("run1"), {"uuid": "p"}, kind, "123")
    identificator = body(sent[0])["partijIdentificator"]
    assert (identificator["codeObjecttype"], identificator["codeRegister"]) == (objecttype, register)


def test_random_numbers_have_their_format():
    bsn = openklant.random_bsn()
    weighted = sum(int(d) * w for d, w in zip(bsn, [9, 8, 7, 6, 5, 4, 3, 2, -1], strict=True))
    assert len(bsn) == 9 and weighted % 11 == 0
    assert len(openklant.random_kvk_nummer()) == 8
    assert len(openklant.random_nummer()) == 10


def test_delete_zaak_with_documents_accepts_500_once_the_zaak_is_gone(fake_http):
    sent = fake_http(
        {
            "GET /v1/zaken/api/v1/zaakinformatieobjecten": results({"informatieobject": f"{API}/doc"}),
            "DELETE /v1/zaken/api/v1/zaken/z1": (500, {}),
            "GET /v1/zaken/api/v1/zaken/z1": (404, {}),
            "DELETE /v1/doc": (204, {}),
        }
    )
    openzaak.delete_zaak(api(), ZAAK, with_documents=True)
    assert calls(sent) == [
        ("GET", "/zaken/api/v1/zaakinformatieobjecten"),
        ("DELETE", "/zaken/api/v1/zaken/z1"),
        ("GET", "/zaken/api/v1/zaken/z1"),
        ("DELETE", "/doc"),
    ]


def test_zaaktype_parts_and_close_zaak(fake_http):
    catalogi = "/v1/catalogi/api/v1"
    sent = fake_http(
        {
            f"{catalogi}/statustypen": results({"url": "st2", "volgnummer": 2}, {"url": "st1", "volgnummer": 1}),
            f"{catalogi}/roltypen": results({"omschrijvingGeneriek": "initiator", "url": "rt"}),
            f"{catalogi}/eigenschappen": results({"naam": "e", "url": "eu"}),
            f"{catalogi}/besluittypen": results({"url": "bt"}),
            f"{catalogi}/resultaattypen": results({"url": "rs"}),
            "POST /v1/zaken/api/v1/resultaten": (201, {}),
            "POST /v1/zaken/api/v1/statussen": (201, {}),
            "GET /v1/zaken/api/v1/zaken/z1": (200, {"url": ZAAK, "einddatum": "2026-10-19"}),
        }
    )
    parts = openzaak.zaaktype_parts(api(), {"url": "zt", "informatieobjecttypen": ["iot"]})
    assert [s["url"] for s in parts.statustypen] == ["st1", "st2"]
    assert (parts.roltypen, parts.eigenschappen) == ({"initiator": "rt"}, {"e": "eu"})
    assert (parts.informatieobjecttype, parts.besluittype, parts.resultaattypen) == ("iot", "bt", ["rs"])
    del sent[:]
    assert openzaak.close_zaak(api(), {"url": ZAAK}, parts)["einddatum"] == "2026-10-19"
    assert body(sent[0])["resultaattype"] == "rs"
    assert body(sent[1])["statustype"] == "st2"


def test_clean_up_new_documents_deletes_links_and_documents(fake_http):
    sent = fake_http(
        {
            "GET /v1/zaken/api/v1/zaakinformatieobjecten": results(
                {"url": f"{API}/zio", "informatieobject": f"{API}/doc"}
            ),
            "DELETE /v1/zio": (204, {}),
            "DELETE /v1/doc": (204, {}),
        }
    )
    registry = ResourceRegistry("run1")
    openzaak.clean_up_new_documents(api(), registry, {"url": ZAAK})
    registry.cleanup()
    assert calls(sent)[1:] == [("DELETE", "/zio"), ("DELETE", "/doc")]


def test_delete_klantcontact_tree_deletes_inlined_objects_first(fake_http):
    expand = {
        "hadBetrokkenen": [{"url": f"{API}/b", "digitaleAdressen": [{"url": f"{API}/da"}]}],
        "leiddeTotInterneTaken": [{"url": f"{API}/it"}],
    }
    answers = {"GET /v1/klantcontacten/k": (200, {"_expand": expand})}
    sent = fake_http(answers | {f"DELETE /v1/{p}": (204, {}) for p in ("da", "it", "b", "klantcontacten/k")})
    openklant.delete_klantcontact_tree(api(), f"{API}/klantcontacten/k")
    assert [p for m, p in calls(sent) if m == "DELETE"] == ["/da", "/it", "/b", "/klantcontacten/k"]


def test_delete_klantcontact_tree_of_a_gone_klantcontact_only_looks(fake_http):
    sent = fake_http({"GET /v1/klantcontacten/k": (404, {})})
    openklant.delete_klantcontact_tree(api(), f"{API}/klantcontacten/k")
    assert [m for m, _ in calls(sent)] == ["GET"]


def test_partijen_of_lists_each_partij_once(fake_http):
    identificatoren = [{"identificeerdePartij": {"url": u}} for u in ("p1", "p2", "p1")]
    fake_http({"/v1/partij-identificatoren": results(*identificatoren)})
    assert openklant.partijen_of(api(), "123") == ["p1", "p2"]


def test_expanded_returns_the_inlined_objects(fake_http):
    fake_http({"/v1/partijen/p": (200, {"_expand": {"betrokkenen": [{"n": 1}]}})})
    assert openklant.expanded(api(), f"{API}/partijen/p", "betrokkenen") == [{"n": 1}]


def test_delete_partij_deletes_sub_identificators_before_their_parent(fake_http):
    refs = [{"url": f"{API}/id-kvk"}, {"url": f"{API}/id-vestiging"}]
    sent = fake_http(
        {
            "/v1/digitaleadressen": results({"url": f"{API}/da"}),
            "GET /v1/partijen/p": (200, {"partijIdentificatoren": refs}),
            "GET /v1/id-kvk": (200, {"url": f"{API}/id-kvk", "subIdentificatorVan": None}),
            "GET /v1/id-vestiging": (200, {"url": f"{API}/id-vestiging", "subIdentificatorVan": {"uuid": "kvk"}}),
        }
        | {f"DELETE /v1/{p}": (204, {}) for p in ("da", "id-kvk", "id-vestiging", "partijen/p")}
    )
    openklant.delete_partij(api(), f"{API}/partijen/p")
    assert [p for m, p in calls(sent) if m == "DELETE"] == ["/da", "/id-vestiging", "/id-kvk", "/partijen/p"]


def test_submission_contact_cleanup_deletes_the_tree_by_onderwerp(fake_http):
    paths = ("klantcontacten", "betrokkenen", "digitaleadressen", "onderwerpobjecten")
    answers = {k: v for p in paths for k, v in created(p).items()}
    found = [{"url": f"{API}/klantcontacten/k", "inhoud": "other"}, {"url": f"{API}/klantcontacten/new", "inhoud": "x"}]
    answers |= {"GET /v1/klantcontacten": results(*found), "GET /v1/klantcontacten/new": (404, {})}
    sent = fake_http(answers)
    registry = ResourceRegistry("run1")
    openklant.make_submission_contact(api(), registry, "OF-1", "a@example.invalid")
    assert body(sent[0])["onderwerp"] == "OF-1"
    assert body(sent[3])["onderwerpobjectidentificator"]["codeObjecttype"] == "formulierinzending"
    assert openklant.klantcontacten_about(api(), "OF-1", "x") == [found[1]]
    del sent[:]
    registry.cleanup()
    assert {("GET", "/klantcontacten/k"), ("GET", "/klantcontacten/new")} <= set(calls(sent))


def objecten_env(monkeypatch, found: dict[str, str]) -> Environment:
    monkeypatch.setattr(objecten_module, "run_snippet", lambda *_args: found)
    env = SimpleNamespace(
        kube=None,
        deployment_for=lambda _component: "objecten",
        profile=SimpleNamespace(urls={"objecten": "https://objecten.test"}),
    )
    return cast("Environment", env)


@pytest.mark.parametrize(
    ("found", "url"),
    [
        ({"uuid": "u1"}, "https://objecten.test/api/v2/objecttypes/u1"),
        ({"url": "https://objecttypen.test/api/v2/objecttypes/u2"}, "https://objecttypen.test/api/v2/objecttypes/u2"),
    ],
)
def test_objecttype_url_from_uuid_or_url(monkeypatch, found, url):
    assert objecttype_url(objecten_env(monkeypatch, found), "VAC") == url


def test_objecttype_url_of_an_unknown_objecttype(monkeypatch):
    with pytest.raises(LookupError, match="no objecttype VAC"):
        objecttype_url(objecten_env(monkeypatch, {}), "VAC")


def test_productaanvraag_and_logboek_cleanup(fake_http):
    sent = fake_http(
        created("objects")
        | {"GET /v1/objects": results({"url": f"{API}/objects/log"}), "DELETE /v1/objects/log": (204, {})}
    )
    registry = ResourceRegistry("run1")
    make_productaanvraag(api(), registry, "ot", "pat", "OF-1")
    clean_up_logboek(api(), registry, "lt", "it1")
    registry.cleanup()
    record = body(sent[0])["record"]
    assert (record["data"]["type"], record["data"]["bron"]["kenmerk"]) == ("pat", "OF-1")
    assert "heeftBetrekkingOp__objectId__exact__it1" in sent[1].url
    assert calls(sent)[1:] == [("GET", "/objects"), ("DELETE", "/objects/log"), ("DELETE", "/objects/new")]


def test_abonnement_sends_the_callback_auth(fake_http):
    sent = fake_http(created("abonnement"))
    make_abonnement(api(), ResourceRegistry("run1"), "https://cb.test/", "zaken", {"bronorganisatie": "1"})
    assert body(sent[0]) == {
        "callbackUrl": "https://cb.test/",
        "auth": CALLBACK_AUTH,
        "kanalen": [{"naam": "zaken", "filters": {"bronorganisatie": "1"}}],
    }


def test_document_in_parts_uploads_each_part_without_json_content_type(fake_http):
    eio = "/v1/documenten/api/v1/enkelvoudiginformatieobjecten"
    parts = [{"url": f"{API}/deel/1", "omvang": 3}, {"url": f"{API}/deel/2", "omvang": 2}]
    created_document = {"url": f"{API}{eio[3:]}/d", "lock": "L", "bestandsdelen": parts}
    sent = fake_http({f"POST {eio}": (201, created_document), "/v1/deel/1": (200, {}), "/v1/deel/2": (200, {})})
    document = openzaak.make_document_in_parts(api(), ResourceRegistry("run1"), "iot", b"abcde", bestandsnaam="x.bin")
    assert document["lock"] == "L"
    assert body(sent[0])["bestandsomvang"] == 5
    assert "inhoud" not in body(sent[0])
    uploads = sent[1:]
    assert [u.url for u in uploads] == [p["url"] for p in parts]
    assert all("multipart/form-data" in u.headers["Content-Type"] for u in uploads)
    assert b"abc" in uploads[0].body and b"de" in uploads[1].body
