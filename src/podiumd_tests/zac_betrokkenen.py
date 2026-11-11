"""The initiator and betrokkenen of a zaak in ZAC, as its UI adds and removes them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from podiumd_tests.json_data import section
from podiumd_tests.responses import get_entries

if TYPE_CHECKING:
    import requests

    from podiumd_tests.json_data import JsonObject


def betrokkene_roltype(http: requests.Session, zac_url: str, zaak: JsonObject, rol: str) -> JsonObject:
    """Return the first roltype ZAC offers for betrokkenen of the zaak whose naam starts with rol (case ignored).

    By prefix: a zaaktype may say "Belanghebbende e2e", and several share a generic role.
    """
    zaaktype = section(zaak, "zaaktype")["uuid"]
    offered = get_entries(http, f"{zac_url}/rest/klanten/roltype/{zaaktype}/betrokkene")
    return next(roltype for roltype in offered if str(roltype["naam"]).lower().startswith(rol))


def add_betrokkene(
    http: requests.Session, zac_url: str, zaak: JsonObject, roltype: JsonObject, identificatie: JsonObject
) -> requests.Response:
    """Add a betrokkene (BetrokkeneIdentificatie) with the roltype to the zaak; ZAC's answer."""
    body = {
        "zaakUUID": zaak["uuid"],
        "roltypeUUID": roltype["uuid"],
        "roltoelichting": "podiumd-tests",
        "betrokkeneIdentificatie": identificatie,
    }
    return http.post(f"{zac_url}/rest/zaken/betrokkene", json=body)


def betrokkenen(http: requests.Session, zac_url: str, zaak: JsonObject) -> list[JsonObject]:
    """Return the betrokkenen ZAC lists with the zaak, each with its rolid and roltype."""
    return get_entries(http, f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/betrokkene")


def _reden_body(reden: str | None) -> dict[str, str]:
    """ZAC's reden body; None sends none."""
    return {} if reden is None else {"reden": reden}


def ontkoppel_betrokkene(
    http: requests.Session, zac_url: str, betrokkene: JsonObject, reden: str | None
) -> requests.Response:
    """Remove the betrokkene (as betrokkenen lists it) from its zaak with the reden; ZAC's answer."""
    return http.delete(f"{zac_url}/rest/zaken/betrokkene/{betrokkene['rolid']}", json=_reden_body(reden))


def wijzig_initiator(
    http: requests.Session, zac_url: str, zaak: JsonObject, identificatie: JsonObject, toelichting: str | None
) -> requests.Response:
    """Make the BetrokkeneIdentificatie the zaak's initiator; ZAC needs a toelichting to replace one; ZAC's answer."""
    body: dict[str, object] = {"zaakUUID": zaak["uuid"], "betrokkeneIdentificatie": identificatie}
    if toelichting is not None:
        body["toelichting"] = toelichting
    return http.patch(f"{zac_url}/rest/zaken/initiator", json=body)


def ontkoppel_initiator(http: requests.Session, zac_url: str, zaak: JsonObject, reden: str | None) -> requests.Response:
    """Remove the zaak's initiator with the reden; ZAC's answer."""
    return http.delete(f"{zac_url}/rest/zaken/{zaak['uuid']}/initiator", json=_reden_body(reden))
