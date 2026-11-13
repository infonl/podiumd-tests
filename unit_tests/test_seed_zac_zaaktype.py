"""Unit tests for podiumd-tests' own zaaktype in ZAC."""

import json

from datetime import date
from datetime import timedelta
from types import SimpleNamespace
from typing import cast

import pytest
import requests

from podiumd_tests.clients.api import ApiClient
from podiumd_tests.environment import Environment
from podiumd_tests.seed import zac_zaaktype
from podiumd_tests.seed.catalogi import ZaaktypeTypes
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
    monkeypatch.setattr(zac_zaaktype, "zac_session", lambda *_args: "zac")
    cleared = []
    monkeypatch.setattr(zac_zaaktype, "clear_ztc_cache", lambda _http, url: cleared.append(url))
    sent = fake_http({f"PATCH {ZAAKTYPEN}/v1": (200, {})})
    client = ApiClient(requests.Session(), API, {})
    registry = ResourceRegistry(RUN)
    alg = {"url": "alg"}
    published = zac_zaaktype.publish_zac_zaaktype(env(), client, registry, {}, catalogus=alg, servicenorm="P10D")
    registry.cleanup()
    assert cleared == ["https://zac.test"]
    assert made["catalogus"] == alg
    assert published == {"url": f"{API}{ZAAKTYPEN}/v1", "concept": False}
    assert made["statustypen"] == ("Intake", "Wacht op aanvullende informatie", "In behandeling", "Afgerond")
    assert ("Behandelaar", "behandelaar") in made["roltypen"]
    assert str(made["omschrijving"]).startswith(f"{RUN}-zac-")
    assert made["servicenorm"] == "P10D"
    assert json.loads(sent[-1].body) == {"deelzaaktypen": [f"{API}{ZAAKTYPEN}/v1"]}


def test_publish_zac_zaaktype_links_the_informatieobjecttypen_before_publishing(fake_http, monkeypatch):
    monkeypatch.setattr(
        zac_zaaktype, "make_publishable_zaaktype", lambda *_args, **_fields: {"url": f"{API}{ZAAKTYPEN}/v1"}
    )
    monkeypatch.setattr(zac_zaaktype, "publish", lambda _openzaak, concept: concept)
    links = "/catalogi/api/v1/zaaktype-informatieobjecttypen"
    sent = fake_http({f"PATCH {ZAAKTYPEN}/v1": (200, {}), f"POST {links}": (201, {})})
    client = ApiClient(requests.Session(), API, {})
    zac_zaaktype.publish_zac_zaaktype(env(), client, ResourceRegistry(RUN), {}, informatieobjecttypen=("i1", "i2"))
    assert [json.loads(s.body) for s in sent if s.url.endswith(links)] == [
        {"zaaktype": f"{API}{ZAAKTYPEN}/v1", "informatieobjecttype": "i1", "volgnummer": 1, "richting": "intern"},
        {"zaaktype": f"{API}{ZAAKTYPEN}/v1", "informatieobjecttype": "i2", "volgnummer": 2, "richting": "intern"},
    ]


def test_publish_zac_zaaktype_publishes_its_besluittypen_before_itself(fake_http, monkeypatch):
    monkeypatch.setattr(
        zac_zaaktype, "make_publishable_zaaktype", lambda *_args, **_fields: {"url": f"{API}{ZAAKTYPEN}/v1"}
    )
    published = []
    monkeypatch.setattr(zac_zaaktype, "publish", lambda _openzaak, item: published.append(item["url"]) or item)
    fake_http({f"PATCH {ZAAKTYPEN}/v1": (200, {})})
    types = ZaaktypeTypes(besluittypen=("b1",))
    zac_zaaktype.publish_zac_zaaktype(
        env(), ApiClient(requests.Session(), API, {}), ResourceRegistry(RUN), {}, types=types
    )
    assert published == ["b1", f"{API}{ZAAKTYPEN}/v1"]


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
    monkeypatch.setattr(zac_zaaktype, "add_entity_type", lambda _s, _u, name: calls.append(("add", name)) or "e1")
    monkeypatch.setattr(
        zac_zaaktype, "ensure_domain", lambda _s, _u, name, types: calls.append(("domain", name, types))
    )
    monkeypatch.setattr(zac_zaaktype, "find_entity_type", lambda _s, _u, _name, _kind: "e1")
    monkeypatch.setattr(zac_zaaktype, "delete_entity_type", lambda _s, _u, entity: calls.append(("delete", entity)))
    registry = ResourceRegistry(RUN)
    zac_zaaktype.grant_zaaktype(env(), registry, "zt")
    registry.cleanup()
    assert calls == [("add", "zt"), ("domain", "ptest-bootstrap", ["e1"]), ("delete", "e1")]


def test_forget_leaves_pabc_alone_without_the_entity_type(monkeypatch):
    monkeypatch.setattr(zac_zaaktype, "admin_session", lambda *_args: "pabc")
    monkeypatch.setattr(zac_zaaktype, "find_entity_type", lambda *_args: None)
    deleted = []
    monkeypatch.setattr(zac_zaaktype, "delete_entity_type", lambda *args: deleted.append(args))
    zac_zaaktype.forget_entity_types(env(), "zt")
    assert deleted == []


def test_role_group_carries_the_functional_role_and_cleanup_deletes_it_by_name(monkeypatch):
    calls = []
    admin = SimpleNamespace(
        create_group=lambda name, roles: calls.append(("create", name, roles)) or "g1",
        delete_group_named=lambda name: calls.append(("delete", name)),
    )
    monkeypatch.setattr(zac_zaaktype, "for_environment", lambda _env: admin)
    registry = ResourceRegistry(RUN)
    name = zac_zaaktype.make_role_group(env(), registry, "raadpleger")
    assert name.startswith(f"{RUN}-zac-raadpleger-")
    assert name != zac_zaaktype.make_role_group(env(), ResourceRegistry(RUN), "raadpleger")
    assert len(zac_zaaktype.make_role_group(env(), ResourceRegistry(RUN), "raadpleger", 255)) == 255
    registry.cleanup()
    assert calls[0] == ("create", name, ("ptest-bootstrap-zac-raadpleger",))
    assert calls[-1] == ("delete", name)


def test_group_member_is_a_run_tagged_user_in_the_group_that_cleanup_deletes(monkeypatch):
    calls = []
    admin = SimpleNamespace(
        new_password=lambda: "pw",
        create_user=lambda username, _password, _attributes: calls.append(("create", username)) or "u1",
        group_id={"ptest-g": "g1"}.get,
        join_group=lambda user, group: calls.append(("join", user, group)),
        delete_user_named=lambda username: calls.append(("delete", username)),
    )
    monkeypatch.setattr(zac_zaaktype, "for_environment", lambda _env: admin)
    registry = ResourceRegistry(RUN)
    lid, password = zac_zaaktype.make_group_member(env(), registry, "ptest-g")
    assert lid.startswith(f"{RUN}-zac-lid-")
    assert password == admin.new_password()
    registry.cleanup()
    assert calls == [("create", lid), ("join", "u1", "g1"), ("delete", lid)]
    with pytest.raises(LookupError, match="Keycloak group ptest-x not found"):
        zac_zaaktype.make_group_member(env(), registry, "ptest-g", "ptest-x")


def test_other_domain_group_maps_a_new_realm_role_in_a_domain_of_its_own(monkeypatch):
    calls = []
    admin = SimpleNamespace(
        create_role=lambda name: calls.append(("role", name)),
        delete_role=lambda name: calls.append(("delete role", name)),
        create_group=lambda name, roles: calls.append(("group", name, roles)),
        delete_group_named=lambda name: calls.append(("delete group", name)),
    )
    monkeypatch.setattr(zac_zaaktype, "for_environment", lambda _env: admin)
    monkeypatch.setattr(zac_zaaktype, "pabc_as_admin", lambda _env: ("pabc", "https://pabc.test"))
    monkeypatch.setattr(zac_zaaktype, "add_entity_type", lambda _pabc, _url, name: f"et-{name}")
    monkeypatch.setattr(zac_zaaktype, "forget_entity_types", lambda _env, *names: calls.append(("forget", *names)))
    monkeypatch.setattr(zac_zaaktype, "ensure_domain", lambda _pabc, _url, name, types: f"d-{name}-{types[0]}")

    def functional_role(_pabc, _url, name, application, roles, domain):
        calls.append(("functional", name, application, roles, domain))

    monkeypatch.setattr(zac_zaaktype, "ensure_functional_role", functional_role)
    monkeypatch.setattr(
        zac_zaaktype,
        "delete_roles_and_domain",
        lambda _pabc, _url, roles, domain: calls.append(("drop", roles, domain)),
    )
    registry = ResourceRegistry(RUN)
    name = zac_zaaktype.make_other_domain_group(env(), registry, "raadpleger")
    assert name.startswith(f"{RUN}-zac-domein-")
    registry.cleanup()
    assert calls == [
        ("role", name),
        ("functional", name, "zaakafhandelcomponent", ("raadpleger",), f"d-{name}-et-{name}"),
        ("group", name, (name,)),
        ("delete group", name),
        ("drop", [name], name),
        ("forget", name),
        ("delete role", name),
    ]


def test_make_zac_zaaktype_configures_the_granted_zaaktype_in_the_admins_group(monkeypatch):
    calls = []
    zaaktype = {"url": f"{API}{ZAAKTYPEN}/zt1", "omschrijving": "o"}
    monkeypatch.setattr(zac_zaaktype, "publish_zac_zaaktype", lambda *_args, **_fields: zaaktype)
    monkeypatch.setattr(zac_zaaktype, "grant_zaaktype", lambda _env, _reg, name: calls.append(("grant", name)))
    monkeypatch.setattr(zac_zaaktype, "zac_session", lambda *_args: "zac")
    monkeypatch.setattr(zac_zaaktype, "user_groups", lambda _http, _url: ["g1", "g2"])

    def configure(_http, _url, uuid, groep):
        calls.append(("configure", uuid, groep))
        return {"id": 1}

    monkeypatch.setattr(zac_zaaktype, "configure_zaaktype", configure)
    registry = ResourceRegistry(RUN)
    assert zac_zaaktype.make_zac_zaaktype(env(), None, registry, {}) == {"id": 1}  # pyright: ignore[reportArgumentType]
    registry.cleanup()
    assert calls == [("grant", "o"), ("configure", "zt1", "g1")]


def test_other_domain_group_holds_the_number_of_zaaktypen_and_forgets_them_at_once(monkeypatch):
    domains = []
    admin = SimpleNamespace(
        create_role=print, delete_role=print, create_group=lambda *_a: None, delete_group_named=print
    )
    monkeypatch.setattr(zac_zaaktype, "for_environment", lambda _env: admin)
    monkeypatch.setattr(zac_zaaktype, "pabc_as_admin", lambda _env: ("pabc", "https://pabc.test"))
    monkeypatch.setattr(zac_zaaktype, "add_entity_type", lambda _pabc, _url, name: f"et-{name}")
    monkeypatch.setattr(zac_zaaktype, "ensure_domain", lambda _pabc, _url, _name, types: domains.append(types) or "d")
    monkeypatch.setattr(zac_zaaktype, "ensure_functional_role", lambda *_args: None)
    name = zac_zaaktype.make_other_domain_group(env(), ResourceRegistry(RUN), "raadpleger", zaaktypen=3)
    assert domains == [[f"et-{name}", f"et-{name}-001", f"et-{name}-002"]]


def test_other_domain_holds_the_gemeenten_and_cleanup_forgets_them(monkeypatch):
    domains, forgotten = [], []
    admin = SimpleNamespace(
        create_role=lambda _name: None,
        delete_role=lambda _name: None,
        create_group=lambda _name, _roles: None,
        delete_group_named=lambda _name: None,
    )
    monkeypatch.setattr(zac_zaaktype, "for_environment", lambda _env: admin)
    monkeypatch.setattr(zac_zaaktype, "pabc_as_admin", lambda _env: ("pabc", "https://pabc.test"))
    monkeypatch.setattr(
        zac_zaaktype,
        "add_entity_type",
        lambda _pabc, _url, entity, kind="ZAAKTYPE", name=None: f"{kind}-{name or entity}",
    )
    monkeypatch.setattr(zac_zaaktype, "ensure_domain", lambda _pabc, _url, _name, types: domains.append(types) or "d")
    monkeypatch.setattr(zac_zaaktype, "ensure_functional_role", lambda *_args: None)
    monkeypatch.setattr(zac_zaaktype, "delete_roles_and_domain", lambda *_args: None)
    monkeypatch.setattr(
        zac_zaaktype, "forget_entity_types", lambda _env, *ids, kind="ZAAKTYPE": forgotten.append((kind, *ids))
    )
    registry = ResourceRegistry(RUN)
    name = zac_zaaktype.make_other_domain_group(env(), registry, "brp_zoeken", gemeenten={"0530": "Hellevoetsluis"})
    registry.cleanup()
    assert domains == [[f"ZAAKTYPE-{name}", "GEMEENTE-Hellevoetsluis"]]
    assert ("GEMEENTE", "0530") in forgotten


def test_forget_deletes_each_entity_type_with_one_login(monkeypatch):
    logins, deleted = [], []
    monkeypatch.setattr(zac_zaaktype, "pabc_as_admin", lambda _env: logins.append(1) or ("pabc", "https://pabc.test"))
    monkeypatch.setattr(zac_zaaktype, "find_entity_type", lambda _s, _u, name, _kind: {"a": "e1", "b": "e2"}.get(name))
    monkeypatch.setattr(zac_zaaktype, "delete_entity_type", lambda _s, _u, entity: deleted.append(entity))
    zac_zaaktype.forget_entity_types(env(), "a", "x", "b")
    assert (logins, deleted) == ([1], ["e1", "e2"])
