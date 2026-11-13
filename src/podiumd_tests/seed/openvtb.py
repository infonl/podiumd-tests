"""Open VTB test data; every factory registers its deleter."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry


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
