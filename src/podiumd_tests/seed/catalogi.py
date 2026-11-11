"""Throwaway catalogus types in the test catalogus that tests publish, and their removal.

The Catalogi API refuses to delete a published type, so cleanup and sweep delete them with snippet
openzaak_catalogi_types; that snippet only touches names carrying a run tag.
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.bootstrap.names import TEST_CATALOGUS_DOMEIN
from podiumd_tests.bootstrap.names import TEST_CATALOGUS_RSIN
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.results import RUN_TAG
from podiumd_tests.results import TAG_PREFIX
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import make_concept_zaaktype
from podiumd_tests.seed.openzaak import today

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

SNIPPET = "openzaak_catalogi_types"
CATALOGUS = {"domein": TEST_CATALOGUS_DOMEIN, "rsin": TEST_CATALOGUS_RSIN}


def _params(name: str) -> dict[str, object]:
    if not RUN_TAG.search(name):
        msg = f"refusing to delete catalogus type {name}: it carries no run tag"
        raise ValueError(msg)
    return {**CATALOGUS, "action": "delete", "name": name}


def forget_catalogus_type(env: Environment, registry: ResourceRegistry, name: str) -> None:
    """Delete, at cleanup, the zaaktype (by identificatie) or besluittype or informatieobjecttype (by omschrijving)."""
    deployment = env.deployment_for("openzaak")
    registry.add_snippet(f"catalogus type {name}", env.kube, deployment, SNIPPET, _params(name))


def remove_catalogus_type(env: Environment, name: str) -> None:
    """Delete a run-tagged catalogus type, published or not, with what belongs to it."""
    run_snippet(env.kube, env.deployment_for("openzaak"), SNIPPET, _params(name))


def tagged_catalogus_types(env: Environment) -> list[str]:
    """Return the names of the test catalogus's types that start with ptest-, bootstrap ones included."""
    params: dict[str, object] = {**CATALOGUS, "action": "list", "prefix": TAG_PREFIX}
    found = run_snippet(env.kube, env.deployment_for("openzaak"), SNIPPET, params)
    return [str(name) for name in cast("list[object]", found)]


def publish(openzaak: ApiClient, catalogus_type: JsonObject) -> JsonObject:
    """Publish a concept zaaktype, besluittype or informatieobjecttype; the published type."""
    openzaak.request("POST", f"{catalogus_type['url']}/publish", HTTPStatus.OK, json={})
    return openzaak.get(str(catalogus_type["url"]))


@dataclass(frozen=True)
class ZaaktypeTypes:
    """The statustypen (the last is the eindstatus) and (omschrijving, omschrijvingGeneriek) roltypen of a zaaktype.

    The defaults are what publishing needs.
    """

    statustypen: tuple[str, ...] = ("Ontvangen", "Afgehandeld")
    roltypen: tuple[tuple[str, str], ...] = (("Initiator", "initiator"),)


PUBLISHABLE = ZaaktypeTypes()


def make_publishable_zaaktype(
    env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    template: JsonObject,
    types: ZaaktypeTypes = PUBLISHABLE,
    /,
    **fields: object,
) -> JsonObject:
    """Create a concept zaaktype with what publishing needs, copied from a published template zaaktype.

    The types and a resultaattype "Afgehandeld" of the template's selectielijst; children are not registered: they go
    with the zaaktype, and the API refuses to delete those of a published one.
    """
    resultaattype = openzaak.list(f"{CATALOGI}/resultaattypen", {"zaaktype": str(template["url"])})[0]
    zaaktype = make_concept_zaaktype(
        openzaak,
        registry,
        str(template["catalogus"]),
        selectielijstProcestype=template["selectielijstProcestype"],
        **fields,
    )
    forget_catalogus_type(env, registry, str(zaaktype["identificatie"]))
    url = zaaktype["url"]
    for volgnummer, omschrijving in enumerate(types.statustypen, start=1):
        openzaak.post(
            f"{CATALOGI}/statustypen", {"zaaktype": url, "omschrijving": omschrijving, "volgnummer": volgnummer}
        )
    for omschrijving, generiek in types.roltypen:
        openzaak.post(
            f"{CATALOGI}/roltypen", {"zaaktype": url, "omschrijving": omschrijving, "omschrijvingGeneriek": generiek}
        )
    copied = ("resultaattypeomschrijving", "selectielijstklasse", "archiefnominatie", "archiefactietermijn")
    body = {key: resultaattype[key] for key in copied}
    procedure = {"afleidingswijze": "afgehandeld", "procestermijn": None}
    openzaak.post(
        f"{CATALOGI}/resultaattypen",
        {**body, "zaaktype": url, "omschrijving": "Afgehandeld", "brondatumArchiefprocedure": procedure},
    )
    return openzaak.get(str(url))


def make_concept_iot(env: Environment, openzaak: ApiClient, registry: ResourceRegistry, catalogus: str) -> JsonObject:
    """Create a run-tagged concept informatieobjecttype in a catalogus."""
    omschrijving = registry.tagged("iot")
    forget_catalogus_type(env, registry, omschrijving)
    body = {
        "catalogus": catalogus,
        "omschrijving": omschrijving,
        "vertrouwelijkheidaanduiding": "openbaar",
        "beginGeldigheid": today(),
        "informatieobjectcategorie": "podiumd-tests",
    }
    return openzaak.post(f"{CATALOGI}/informatieobjecttypen", body)


def make_concept_besluittype(
    env: Environment, openzaak: ApiClient, registry: ResourceRegistry, catalogus: str, **fields: object
) -> JsonObject:
    """Create a run-tagged concept besluittype in a catalogus."""
    omschrijving = registry.tagged("besluittype")
    forget_catalogus_type(env, registry, omschrijving)
    body: dict[str, object] = {
        "catalogus": catalogus,
        "omschrijving": omschrijving,
        "zaaktypen": [],
        "informatieobjecttypen": [],
        "publicatieIndicatie": False,
        "beginGeldigheid": today(),
        **fields,
    }
    return openzaak.post(f"{CATALOGI}/besluittypen", body)
