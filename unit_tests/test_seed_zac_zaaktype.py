"""Unit tests for podiumd-tests' own zaaktype in ZAC."""

import json

from datetime import date
from datetime import timedelta
from types import SimpleNamespace
from typing import cast

import requests

from podiumd_tests.clients.api import ApiClient
from podiumd_tests.environment import Environment
from podiumd_tests.seed import zac_zaaktype
from podiumd_tests.seed.registry import ResourceRegistry

API = "https://api.example.test"
ZAAKTYPEN = "/catalogi/api/v1/zaaktypen"
RUN = "ptest-2611111200abcd"


def env() -> Environment:
    profile = SimpleNamespace(urls={"zac": "https://zac.test", "pabc": "https://pabc.test"})
    return cast("Environment", SimpleNamespace(profile=profile, credentials=SimpleNamespace(get=lambda _key: "pw")))


def test_publish_zac_zaaktype_gives_zacs_types_and_itself_as_deelzaaktype(fake_http, monkeypatch):
    made = {}

    def make(_env, _openzaak, _registry, _template, types, **fields):
        made.update(fields, statustypen=types.statustypen, roltypen=types.roltypen)
        return {"url": f"{API}{ZAAKTYPEN}/v1"}

    monkeypatch.setattr(zac_zaaktype, "make_publishable_zaaktype", make)
    monkeypatch.setattr(zac_zaaktype, "publish", lambda _openzaak, concept: {**concept, "concept": False})
    sent = fake_http({f"PATCH {ZAAKTYPEN}/v1": (200, {})})
    client = ApiClient(requests.Session(), API, {})
    published = zac_zaaktype.publish_zac_zaaktype(env(), client, ResourceRegistry(RUN), {}, servicenorm="P10D")
    assert published == {"url": f"{API}{ZAAKTYPEN}/v1", "concept": False}
    assert made["statustypen"] == ("Intake", "In behandeling", "Afgerond")
    assert ("Behandelaar", "behandelaar") in made["roltypen"]
    assert str(made["omschrijving"]).startswith(f"{RUN}-zac-")
    assert made["servicenorm"] == "P10D"
    assert json.loads(sent[-1].body) == {"deelzaaktypen": [f"{API}{ZAAKTYPEN}/v1"]}


def test_publish_new_version_ends_the_old_one_yesterday_and_updates_the_new_one(fake_http, monkeypatch):
    published = {}

    def publish(_env, _openzaak, _registry, _template, **fields):
        published.update(fields)
        return {"url": f"{API}{ZAAKTYPEN}/v2"}

    monkeypatch.setattr(zac_zaaktype, "publish_zac_zaaktype", publish)
    monkeypatch.setattr(zac_zaaktype, "today", lambda: "2026-11-11")
    sent = fake_http({f"PATCH {ZAAKTYPEN}/v1": (200, {}), f"PATCH {ZAAKTYPEN}/v2": (200, {"url": "v2"})})
    client = ApiClient(requests.Session(), API, {})
    old = {"url": f"{API}{ZAAKTYPEN}/v1", "identificatie": "i", "omschrijving": "o", "servicenorm": None}
    assert zac_zaaktype.publish_new_version(env(), client, ResourceRegistry(RUN), {}, old) == {"url": "v2"}
    assert published == {
        "identificatie": "i",
        "omschrijving": "o",
        "servicenorm": None,
        "beginGeldigheid": "2026-11-11",
    }
    yesterday = (date(2026, 11, 11) - timedelta(days=1)).isoformat()
    assert [json.loads(s.body) for s in sent] == [{"eindeGeldigheid": yesterday}, {"eindeGeldigheid": None}]


def test_grant_adds_the_entity_type_to_the_domain_and_cleanup_forgets_it(monkeypatch):
    calls = []
    monkeypatch.setattr(zac_zaaktype, "admin_session", lambda *_args: "pabc")
    monkeypatch.setattr(
        zac_zaaktype, "add_zaaktype_entity_type", lambda _s, _u, name: calls.append(("add", name)) or "e1"
    )
    monkeypatch.setattr(
        zac_zaaktype, "ensure_domain", lambda _s, _u, name, types: calls.append(("domain", name, types))
    )
    monkeypatch.setattr(zac_zaaktype, "zaaktype_entity_type", lambda _s, _u, _name: "e1")
    monkeypatch.setattr(zac_zaaktype, "delete_entity_type", lambda _s, _u, entity: calls.append(("delete", entity)))
    registry = ResourceRegistry(RUN)
    zac_zaaktype.grant_zaaktype(env(), registry, "zt")
    registry.cleanup()
    assert calls == [("add", "zt"), ("domain", "ptest-bootstrap", ["e1"]), ("delete", "e1")]


def test_forget_leaves_pabc_alone_without_the_entity_type(monkeypatch):
    monkeypatch.setattr(zac_zaaktype, "admin_session", lambda *_args: "pabc")
    monkeypatch.setattr(zac_zaaktype, "zaaktype_entity_type", lambda *_args: None)
    deleted = []
    monkeypatch.setattr(zac_zaaktype, "delete_entity_type", lambda *args: deleted.append(args))
    zac_zaaktype.forget_zaaktype(env(), "zt")
    assert deleted == []


def test_role_group_carries_the_functional_role_and_cleanup_deletes_it(monkeypatch):
    calls = []
    admin = SimpleNamespace(
        create_group=lambda name, roles: calls.append(("create", name, roles)) or "g1",
        delete_group=lambda group: calls.append(("delete", group)),
    )
    monkeypatch.setattr(zac_zaaktype, "for_environment", lambda _env: admin)
    registry = ResourceRegistry(RUN)
    assert zac_zaaktype.make_role_group(env(), registry, "raadpleger") == f"{RUN}-zac-raadpleger"
    registry.cleanup()
    assert calls == [
        ("create", f"{RUN}-zac-raadpleger", ("ptest-bootstrap-zac-raadpleger",)),
        ("delete", "g1"),
    ]


def test_make_zac_zaaktype_configures_the_granted_zaaktype_in_the_admins_group(monkeypatch):
    calls = []
    zaaktype = {"url": f"{API}{ZAAKTYPEN}/zt1", "omschrijving": "o"}
    monkeypatch.setattr(zac_zaaktype, "publish_zac_zaaktype", lambda *_args, **_fields: zaaktype)
    monkeypatch.setattr(zac_zaaktype, "grant_zaaktype", lambda _env, _reg, name: calls.append(("grant", name)))
    monkeypatch.setattr(zac_zaaktype, "zac_session", lambda *_args: "zac")
    monkeypatch.setattr(zac_zaaktype, "user_groups", lambda _http, _url: ["g1", "g2"])
    monkeypatch.setattr(zac_zaaktype, "clear_ztc_cache", lambda _http, url: calls.append(("clear", url)))

    def configure(_http, _url, uuid, groep):
        calls.append(("configure", uuid, groep))
        return {"id": 1}

    monkeypatch.setattr(zac_zaaktype, "configure_zaaktype", configure)
    registry = ResourceRegistry(RUN)
    assert zac_zaaktype.make_zac_zaaktype(env(), None, registry, {}) == {"id": 1}  # pyright: ignore[reportArgumentType]
    registry.cleanup()
    assert calls == [("grant", "o"), ("configure", "zt1", "g1"), ("clear", "https://zac.test")]
