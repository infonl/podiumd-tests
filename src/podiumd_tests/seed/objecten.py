"""Objecten test data; every factory registers its deleter."""

from __future__ import annotations

import json
import secrets

from importlib.resources import files
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.bootstrap.bpmn import uuid_of
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.json_data import strings
from podiumd_tests.seed.openzaak import today
from podiumd_tests.seed.tagged_types import TaggedTypes
from podiumd_tests.zac import notificatie

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry


def objecttype_url(env: Environment, name: str) -> str:
    """Return the URL Objecten knows an objecttype by; LookupError when it has none.

    Open Object serves its objecttypes on its own API.
    """
    found = cast(
        "dict[str, str]",
        run_snippet(env.kube, env.deployment_for("objecten"), "objecten_objecttype", {"name": name}),
    )
    if "uuid" in found:
        return f"{env.profile.urls['objecten']}/api/v2/objecttypes/{found['uuid']}"
    if "url" not in found:
        msg = f"Objecten has no objecttype {name}"
        raise LookupError(msg)
    return found["url"]


def named_objecttypes(objecttypen: ApiClient, name: str) -> list[JsonObject]:
    """Return the objecttypes the Objecttypen API lists with exactly this name."""
    return [found for found in objecttypen.list("objecttypes", {"name": name}) if found.get("name") == name]


def newest_version(objecttypen: ApiClient, objecttype: JsonObject) -> JsonObject:
    """Return the objecttype's version with the highest number."""
    versions = strings(objecttype.get("versions"))
    return objecttypen.get(max(versions, key=lambda url: int(uuid_of(url))))


def dimpact_productaanvraag_schema() -> JsonObject:
    """Return Dimpact's Productaanvraag-Dimpact JSON schema.

    Copied unchanged (CC0 1.0) from https://codeberg.org/Dimpact/objecttypes at commit
    675666d9741170fca200fef4527fb1ea6ac6ac76 (2026-07-09): Productaanvraag/productaanvraag-dimpact.json.
    """
    text = files("podiumd_tests.seed").joinpath("productaanvraag-dimpact.json").read_text(encoding="utf-8")
    return cast("JsonObject", json.loads(text))


OBJECTTYPES = TaggedTypes("objecttype", "objecttypen", "objecttypen_tagged")
# A JSON schema every object meets.
ANY_OBJECT = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}


def make_objecttype(env: Environment, objecttypen: ApiClient, registry: ResourceRegistry, status: str) -> JsonObject:
    """Create a run-tagged objecttype with one version of that status (draft or published); the version."""
    name = registry.tagged(f"objecttype-{secrets.token_hex(3)}")
    objecttype = objecttypen.post("objecttypes", {"name": name, "namePlural": name})
    OBJECTTYPES.forget(env, registry, name)
    return objecttypen.post(f"{objecttype['url']}/versions", {"jsonSchema": ANY_OBJECT, "status": status})


def make_granted_objecttype(
    env: Environment, registry: ResourceRegistry, schema: Mapping[str, object], tokens: Sequence[str]
) -> str:
    """Create a run-tagged objecttype with a published version 1 whose Objecten tokens may write it; its name.

    Through Django: only there Open Object grants a token rights on an objecttype.
    """
    name = registry.tagged(f"objecttype-{secrets.token_hex(3)}")
    OBJECTTYPES.forget(env, registry, name)
    grants = dict.fromkeys(tokens, "read_and_write")
    params: dict[str, object] = {"action": "apply", "name": name, "schema": dict(schema), "grants": grants}
    found = run_snippet(env.kube, env.deployment_for("objecttypen"), "objecttypen_published", params)
    notes = cast("dict[str, list[str]]", found).get("notes")
    if notes:
        msg = f"objecttype {name}: {'; '.join(notes)}"
        raise AssertionError(msg)
    return name


def make_object(
    objecten: ApiClient,
    registry: ResourceRegistry,
    objecttype: str,
    data: Mapping[str, object],
    start_at: str | None = None,
) -> JsonObject:
    """Create an object of an objecttype (the URL Objecten knows), version 1, valid from start_at (default today)."""
    record = {"typeVersion": 1, "data": data, "startAt": start_at or today()}
    body: dict[str, object] = {"type": objecttype, "record": record}
    created = objecten.post("objects", body)
    url = str(created["url"])
    registry.add(f"object {url}", lambda: objecten.delete(url))
    return created


def make_productaanvraag(
    objecten: ApiClient,
    registry: ResourceRegistry,
    objecttype: str,
    productaanvraagtype: str,
    kenmerk: str,
    **fields: object,
) -> JsonObject:
    """Create a productaanvraag object as Open Formulieren's objects API registration writes it, with these fields.

    fields: further fields of the Productaanvraag-Dimpact schema (betrokkenen, zaakgegevens, pdf, bijlagen).
    """
    data: dict[str, object] = {
        "bron": {"naam": "Open Formulieren", "kenmerk": kenmerk},
        "type": productaanvraagtype,
        "aanvraaggegevens": {"melding": {"naamAanvrager": "podiumd-tests", "omschrijving": kenmerk}},
        "taal": "nld",
        **fields,
    }
    return make_object(objecten, registry, objecttype, data)


def created_notificatie(created: JsonObject) -> JsonObject:
    """Return the notificatie Objecten sends for the new object."""
    return notificatie("objecten", "object", str(created["url"]), "create", objectType=created["type"])


def clean_up_logboek(objecten: ApiClient, registry: ResourceRegistry, logboek_type: str, internetaak: str) -> None:
    """Delete, at cleanup, the logboek object ITA creates for an internetaak (uuid) at its first action."""

    def delete() -> None:
        query = {"type": logboek_type, "data_attr": f"heeftBetrekkingOp__objectId__exact__{internetaak}"}
        for found in objecten.list("objects", query):
            objecten.delete(str(found["url"]))

    registry.add(f"ITA logboek of internetaak {internetaak}", delete)
