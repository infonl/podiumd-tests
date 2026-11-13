"""Throwaway catalogus types that tests publish, in the test catalogus or ZAC's own, and their removal.

The Catalogi API refuses to delete a published type, so cleanup and sweep delete them with snippet
openzaak_catalogi_types; that snippet only touches names carrying a run tag.
"""

from __future__ import annotations

import secrets

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

import requests

from podiumd_tests.bootstrap.names import TEST_CATALOGUS_DOMEIN
from podiumd_tests.bootstrap.names import TEST_CATALOGUS_RSIN
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status
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
# Profile setting that allows tests to publish run-tagged zaaktypen in ZAC's own catalogus, which the environment owns.
ZAC_CATALOGUS_WRITES = "zac_catalogus_writes"


def zac_catalogus_domein(env: Environment) -> str:
    """Return the domein of ZAC's own catalogus, whose zaaktypen ZAC lists, checks and signals."""
    return env.variable("zac", "CATALOGUS_DOMEIN")


def written_catalogi(env: Environment) -> list[dict[str, str]]:
    """Return the catalogi tests publish types in: the test catalogus, and ZAC's where the profile allows it."""
    if not env.profile.is_allowed(ZAC_CATALOGUS_WRITES):
        return [CATALOGUS]
    return [CATALOGUS, {"domein": zac_catalogus_domein(env)}]


def _params(name: str, catalogi: list[dict[str, str]]) -> dict[str, object]:
    if not RUN_TAG.search(name):
        msg = f"refusing to delete catalogus type {name}: it carries no run tag"
        raise ValueError(msg)
    return {"catalogi": catalogi, "action": "delete", "name": name}


def forget_catalogus_type(
    env: Environment, registry: ResourceRegistry, name: str, catalogus: JsonObject | None = None
) -> None:
    """Delete, at cleanup, the zaaktype (by identificatie) or besluittype or informatieobjecttype (by omschrijving).

    catalogus: the Open Zaak catalogus it is in; by default the test catalogus.
    """
    where = {field: str(catalogus[field]) for field in ("domein", "rsin")} if catalogus else CATALOGUS
    deployment = env.deployment_for("openzaak")
    registry.add_snippet(f"catalogus type {name}", env.kube, deployment, SNIPPET, _params(name, [where]))


def remove_catalogus_type(env: Environment, name: str) -> None:
    """Delete a run-tagged catalogus type of written_catalogi, published or not, with what belongs to it."""
    run_snippet(env.kube, env.deployment_for("openzaak"), SNIPPET, _params(name, written_catalogi(env)))


def tagged_catalogus_types(env: Environment) -> list[str]:
    """Return the names of the types in written_catalogi that start with ptest-, bootstrap ones included."""
    params: dict[str, object] = {"catalogi": written_catalogi(env), "action": "list", "prefix": TAG_PREFIX}
    found = run_snippet(env.kube, env.deployment_for("openzaak"), SNIPPET, params)
    return [str(name) for name in cast("list[object]", found)]


def publish(openzaak: ApiClient, catalogus_type: JsonObject) -> JsonObject:
    """Publish a concept zaaktype, besluittype or informatieobjecttype; the published type."""
    openzaak.request("POST", f"{catalogus_type['url']}/publish", HTTPStatus.OK, json={})
    return openzaak.get(str(catalogus_type["url"]))


@dataclass(frozen=True)
class ZaaktypeTypes:
    """Statustypen (the last is the eindstatus), (omschrijving, omschrijvingGeneriek) roltypen and text eigenschappen.

    afleidingswijzen: a resultaattype per brondatum afleidingswijze, named after it; eigenschap takes the first
    eigenschap as datumkenmerk, termijn the procestermijn ARCHIEF_PROCESTERMIJN. besluittypen: URLs of concept ones,
    linked: Open Zaak links a concept zaaktype only to concept besluittypen; publish them before the zaaktype.
    archiefactietermijn: False gives resultaattype Afgehandeld none. The defaults are what publishing needs.
    """

    statustypen: tuple[str, ...] = ("Ontvangen", "Afgehandeld")
    roltypen: tuple[tuple[str, str], ...] = (("Initiator", "initiator"),)
    eigenschappen: tuple[str, ...] = ()
    afleidingswijzen: tuple[str, ...] = ()
    besluittypen: tuple[str, ...] = ()
    archiefactietermijn: bool = True


# The procestermijn of a resultaattype with afleidingswijze termijn.
ARCHIEF_PROCESTERMIJN = "P1Y"


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
    with the zaaktype, and the API refuses to delete those of a published one. Field catalogus (a URL) creates it in
    another catalogus than the template's, the test catalogus.
    """
    resultaattype = template_resultaattype(openzaak, template)
    catalogus = str(fields.pop("catalogus", template["catalogus"]))
    zaaktype = make_concept_zaaktype(
        openzaak,
        registry,
        catalogus,
        **{
            "selectielijstProcestype": template["selectielijstProcestype"],
            "besluittypen": list(types.besluittypen),
            **fields,
        },
    )
    where = None if catalogus == template["catalogus"] else openzaak.get(catalogus)
    forget_catalogus_type(env, registry, str(zaaktype["identificatie"]), where)
    url = zaaktype["url"]
    for volgnummer, omschrijving in enumerate(types.statustypen, start=1):
        openzaak.post(
            f"{CATALOGI}/statustypen", {"zaaktype": url, "omschrijving": omschrijving, "volgnummer": volgnummer}
        )
    for omschrijving, generiek in types.roltypen:
        openzaak.post(
            f"{CATALOGI}/roltypen", {"zaaktype": url, "omschrijving": omschrijving, "omschrijvingGeneriek": generiek}
        )
    specificatie: dict[str, object] = {
        "formaat": "tekst",
        "lengte": "20",
        "kardinaliteit": "1",
        "waardenverzameling": [],
    }
    for naam in types.eigenschappen:
        eigenschap: dict[str, object] = {"zaaktype": url, "naam": naam, "definitie": naam, "specificatie": specificatie}
        openzaak.post(f"{CATALOGI}/eigenschappen", eigenschap)
    archief = {key: resultaattype[key] for key in ("archiefnominatie", "archiefactietermijn")}
    if not types.archiefactietermijn:
        archief["archiefactietermijn"] = None
    openzaak.post(f"{CATALOGI}/resultaattypen", resultaattype_body(str(url), resultaattype, **archief))
    if types.afleidingswijzen:
        klasse = {**resultaattype, "selectielijstklasse": selectielijstklasse(str(template["selectielijstProcestype"]))}
        for afleidingswijze in types.afleidingswijzen:
            body = resultaattype_body(
                str(url),
                klasse,
                omschrijving=afleidingswijze,
                brondatumArchiefprocedure=_procedure(afleidingswijze, types),
                **archief,
            )
            openzaak.post(f"{CATALOGI}/resultaattypen", body)
    return openzaak.get(str(url))


def _procedure(afleidingswijze: str, types: ZaaktypeTypes) -> dict[str, object]:
    """Return the brondatumArchiefprocedure of the afleidingswijze, as ZaaktypeTypes describes it."""
    return {
        "afleidingswijze": afleidingswijze,
        "datumkenmerk": types.eigenschappen[0] if afleidingswijze == "eigenschap" else "",
        "procestermijn": ARCHIEF_PROCESTERMIJN if afleidingswijze == "termijn" else None,
    }


def selectielijstklasse(procestype: str) -> str:
    """Return the first Selectielijst resultaat of the procestype without procestermijn.

    Open Zaak allows every brondatum afleidingswijze but afgehandeld only for such a klasse.
    """
    response = requests.get(
        f"{procestype.partition('/procestypen/')[0]}/resultaten", params={"procesType": procestype}, timeout=30
    )
    found = entries(expect_status(response, HTTPStatus.OK).json().get("results"))
    return next(str(item["url"]) for item in found if not item.get("procestermijn"))


def template_resultaattype(openzaak: ApiClient, template: JsonObject) -> JsonObject:
    """Return the first resultaattype of a published zaaktype, whose Selectielijst URLs are valid."""
    return openzaak.list(f"{CATALOGI}/resultaattypen", {"zaaktype": str(template["url"])})[0]


def resultaattype_body(zaaktype: str, selectielijst: JsonObject, **fields: object) -> dict[str, object]:
    """Build a resultaattype "Afgehandeld" with the selectielijstklasse and resultaattypeomschrijving of another."""
    return {
        "zaaktype": zaaktype,
        "omschrijving": "Afgehandeld",
        "resultaattypeomschrijving": selectielijst["resultaattypeomschrijving"],
        "selectielijstklasse": selectielijst["selectielijstklasse"],
        "brondatumArchiefprocedure": {"afleidingswijze": "afgehandeld", "procestermijn": None},
        **fields,
    }


def make_concept_iot(env: Environment, openzaak: ApiClient, registry: ResourceRegistry, catalogus: str) -> JsonObject:
    """Create a run-tagged concept informatieobjecttype in a catalogus."""
    omschrijving = registry.tagged(f"iot-{secrets.token_hex(3)}")
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
    omschrijving = registry.tagged(f"besluittype-{secrets.token_hex(3)}")
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
