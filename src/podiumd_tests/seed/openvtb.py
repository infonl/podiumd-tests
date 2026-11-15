"""Open VTB test data; every factory registers its deleter."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.seed.openzaak import after_period
from podiumd_tests.seed.openzaak import today

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry


# Required details per taak endpoint; the IBAN passes the mod-97 check.
TAAK_DETAILS: dict[str, JsonObject] = {
    "urltaken": {"uitvraagLink": "http://example.invalid/"},
    "betaaltaken": {
        "bedrag": "12.50",
        "transactieomschrijving": "ptest leges",
        "doelrekening": {"naam": "ptest", "iban": "NL91ABNA0417164300"},
    },
    "formuliertaken": {
        "formulierDefinitie": {"components": [{"label": "Bewijsstuk", "key": "bewijsstuk", "type": "textfield"}]}
    },
}

# The fields of an externe taak the Open VTB Taken aansluitprofiel (raadpleegTaak) maps to the Interactie API.
PROFILE_FIELDS = (
    "uuid",
    "titel",
    "toelichting",
    "status",
    "einddatumHandelingsTermijn",
    "isGerelateerdAan",
    "handelingsPerspectief",
    "url",
    "taakSoort",
)


def zaak_urn(zaak: JsonObject) -> str:
    """Return the URN of a zaak by its zaaknummer, unique per bronorganisatie; Open Zaak has no zaak URN."""
    return f"urn:nld:rsin:{zaak['bronorganisatie']}:zaak:zaaknummer:{zaak['identificatie']}"


def taak_body(registry: ResourceRegistry, endpoint: str, **fields: object) -> dict[str, object]:
    """Return a taak for an endpoint (urltaken, ...) with its required fields, titel run-tagged; None drops a field."""
    body: dict[str, object] = {
        "titel": registry.tagged(endpoint),
        "einddatumHandelingsTermijn": after_period(today(), "P14D"),
        "details": TAAK_DETAILS[endpoint],
        **fields,
    }
    return {field: value for field, value in body.items() if value is not None}


def without(body: dict[str, object], field: str) -> dict[str, object]:
    """Return a taak body without a field, at the top or in its details."""
    if field in body:
        return {key: value for key, value in body.items() if key != field}
    details = cast("JsonObject", body["details"])
    return {**body, "details": {key: value for key, value in details.items() if key != field}}


def make_taak(taken: ApiClient, registry: ResourceRegistry, endpoint: str, **fields: object) -> JsonObject:
    """Create a taak as taak_body describes it."""
    taak = taken.post(endpoint, taak_body(registry, endpoint, **fields))
    url = str(taak["url"])
    registry.add(f"openvtb taak {url}", lambda: taken.delete(url))
    return taak


def make_bericht(
    env: Environment, berichten: ApiClient, registry: ResourceRegistry, ontvanger: str, **fields: object
) -> JsonObject:
    """Create a bericht to ontvanger (a URN) of a new berichttype, onderwerp run-tagged; fields override defaults."""
    berichttype = berichten.post(
        "berichttypen",
        {"verantwoordelijkeOrganisatie": "urn:ptest:org", "mijnOverheidBerichtenbox": False, "bijlageTypen": []},
    )
    berichttype_url = str(berichttype["url"])
    registry.add(f"openvtb berichttype {berichttype_url}", lambda: berichten.delete(berichttype_url))
    body = {
        "onderwerp": registry.tagged("bericht"),
        "berichtTekst": "ptest",
        "ontvanger": ontvanger,
        "berichtType": berichttype_url,
        **fields,
    }
    bericht = berichten.post("berichten", body)
    bericht_uuid = str(bericht["uuid"])
    registry.add(f"openvtb bericht {bericht_uuid}", lambda: _delete_bericht(env, bericht_uuid))
    return bericht


def _delete_bericht(env: Environment, bericht: str) -> None:
    """Delete a bericht (uuid), which frees its berichttype, in Open VTB's Django shell: the API answers 405."""
    code = f"from openvtb.components.berichten.models import Bericht\nBericht.objects.filter(uuid={bericht!r}).delete()"
    env.kube.exec_django_shell(env.deployment_for("openvtb"), code)
