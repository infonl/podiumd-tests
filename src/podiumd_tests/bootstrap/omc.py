"""OMC's taak objecttype, and wiring: OMC's abonnement on kanaal zaken, so zaak events reach OMC (TA and
ExternalsPodiumD subscribe it by hand), and, where OMC reads Open VTB, one on Open VTB's bericht CloudEvents.

The abonnement's auth is a token OMC accepts: HS256 with OMC's own secret and its issuer,
audience and user claims, all read from the OMC pod. It expires after VALIDITY; the step then
reports itself missing and bootstrap renews it.
"""

from __future__ import annotations

import json
import time

from dataclasses import dataclass
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.auth.zgw_jwt import hs256_jwt
from podiumd_tests.bootstrap.names import BERICHT_OBJECTTYPE
from podiumd_tests.bootstrap.names import BERICHT_OBJECTTYPE_UUID
from podiumd_tests.bootstrap.names import TAAK_OBJECTTYPE
from podiumd_tests.bootstrap.names import TAAK_OBJECTTYPE_UUID
from podiumd_tests.bootstrap.snippet_step import SnippetStep
from podiumd_tests.clients.platform import opennotificaties_client
from podiumd_tests.mock_server import mock_server_root
from podiumd_tests.responses import url_host
from podiumd_tests.seed.opennotificaties import abonnement_body
from podiumd_tests.seed.opennotificaties import cloudevent_abonnement_body
from podiumd_tests.seed.opennotificaties import delete_abonnement

if TYPE_CHECKING:
    from podiumd_tests.bootstrap.runner import Context
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment

STORE_KEY = "ptest_bootstrap_omc_abonnement_record"
VALIDITY = 365 * 24 * 3600
RENEW_BEFORE = 7 * 24 * 3600
# OMC's endpoint for notifications, the end of its abonnement's callback URL.
LISTEN_PATH = "/Events/Listen"
# The type prefix of Open VTB's bericht CloudEvents.
BERICHT_EVENTS = "nl.overheid.berichten."
# The podiumd chart's ZGW_ENDPOINT_OPENVTB where OMC does not read Open VTB: its host never resolves.
UNSET_HOST_SUFFIX = ".invalid"
# The taak as OMC 2.3.1 reads it first (its vHague TaskObject); the environment owner sets OMC's
# ZGW_VARIABLE_OBJECTTYPE_TASKOBJECTTYPE_UUID to TAAK_OBJECTTYPE_UUID.
TAAK_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["zaak", "title", "status", "verloopdatum", "identificatie"],
    "properties": {
        "zaak": {"type": "string", "format": "uri"},
        "title": {"type": "string"},
        "status": {"enum": ["open", "gesloten"]},
        "verloopdatum": {"type": "string", "format": "date-time"},
        "identificatie": {
            "type": "object",
            "required": ["type", "value"],
            "properties": {"type": {"enum": ["bsn", "kvk"]}, "value": {"type": "string"}},
        },
    },
}


# The bericht OMC 2.3.1's besluit scenario writes for the portal (DecisionMadeScenario.PrepareDataJson), as typeVersion
# ZGW_VARIABLE_OBJECTTYPE_MESSAGEOBJECTTYPE_VERSION: the environment owner sets that to 1 and
# ZGW_VARIABLE_OBJECTTYPE_MESSAGEOBJECTTYPE_UUID to BERICHT_OBJECTTYPE_UUID. publicatiedatum is dd-MM-yyyy;
# identificatie type is "-" when the zaak has no BSN.
BERICHT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "onderwerp",
        "berichtTekst",
        "publicatiedatum",
        "referentie",
        "handelingsperspectief",
        "geopend",
        "berichtType",
        "identificatie",
        "bijlages",
    ],
    "properties": {
        "onderwerp": {"type": "string"},
        "berichtTekst": {"type": "string"},
        "publicatiedatum": {"type": "string"},
        "referentie": {"type": "string", "format": "uri"},
        "handelingsperspectief": {"type": "string"},
        "geopend": {"type": "boolean"},
        "berichtType": {"type": "string"},
        "identificatie": {
            "type": "object",
            "required": ["type", "value"],
            "properties": {"type": {"enum": ["bsn", "-"]}, "value": {"type": "string"}},
        },
        "bijlages": {"type": "array", "items": {"type": "string", "format": "uri"}},
    },
}


def omc_grant(mode: str, ctx: Context) -> dict[str, object]:
    """Return the snippet parameter grants: OMC's Objecten token gets this mode on the objecttype."""
    return {"grants": {ctx.env.variable("omc", "ZGW_AUTH_KEY_OBJECTEN"): mode}}


OMC_TAAK_OBJECTTYPE = SnippetStep(
    "objecttypen-taak",
    ("objecttypen", "objecten", "omc"),
    "objecttypen_published",
    None,
    {"name": TAAK_OBJECTTYPE, "uuid": TAAK_OBJECTTYPE_UUID, "schema": TAAK_SCHEMA},
    opt_in="omc_taak_objecttype",
    context_params=partial(omc_grant, "read_only"),
)
# OMC creates the bericht objects.
OMC_BERICHT_OBJECTTYPE = SnippetStep(
    "objecttypen-bericht",
    ("objecttypen", "objecten", "omc"),
    "objecttypen_published",
    None,
    {"name": BERICHT_OBJECTTYPE, "uuid": BERICHT_OBJECTTYPE_UUID, "schema": BERICHT_SCHEMA},
    opt_in="omc_bericht_objecttype",
    context_params=partial(omc_grant, "read_and_write"),
)


def notify_mock_missing(env: Environment) -> str | None:
    """Skip reason when OMC's Notify base URL is not the mock server, else None."""
    base = env.variable("omc", "NOTIFY_API_BASEURL")
    if url_host(base) == url_host(mock_server_root(env)):
        return None
    return f"OMC's Notify base URL is {base}, not the mock server {mock_server_root(env)}"


def omc_actor_missing(env: Environment, openklant: ApiClient) -> str | None:
    """Skip reason when Open Klant has no actor OMC_ACTOR_ID, which OMC links to each klantcontact it registers."""
    actor = env.variable("omc", "OMC_ACTOR_ID")
    if openklant.request("GET", f"actoren/{actor}", HTTPStatus.OK, HTTPStatus.NOT_FOUND).ok:
        return None
    return f"Open Klant has no actor {actor} (OMC_ACTOR_ID): the environment owner creates it"


def is_reading_openvtb(env: Environment) -> bool:
    """Return whether OMC reads Open VTB: its ZGW_ENDPOINT_OPENVTB is set and not the chart's placeholder."""
    endpoint = env.variable("omc", "ZGW_ENDPOINT_OPENVTB")
    return bool(endpoint) and not url_host(endpoint).endswith(UNSET_HOST_SUFFIX)


def omc_token(env: Environment, now: float) -> str:
    """Return a token OMC's Events/Listen and Notify/Confirm accept, valid for VALIDITY from now."""
    payload = {
        "iss": env.variable("omc", "OMC_AUTH_JWT_ISSUER"),
        "aud": env.variable("omc", "OMC_AUTH_JWT_AUDIENCE"),
        "userId": env.variable("omc", "OMC_AUTH_JWT_USERID"),
        "userName": env.variable("omc", "OMC_AUTH_JWT_USERNAME"),
        "iat": int(now),
        "exp": int(now) + VALIDITY,
    }
    return hs256_jwt(payload, env.credentials.get("omc_jwt_secret"))


def _issuer_and_audience(env: Environment) -> str:
    """Return OMC's issuer and audience, which its token carries: a change makes OMC refuse the abonnement."""
    return f"{env.variable('omc', 'OMC_AUTH_JWT_ISSUER')} {env.variable('omc', 'OMC_AUTH_JWT_AUDIENCE')}"


@dataclass(frozen=True)
class OmcAbonnement:
    """OMC's Events/Listen abonnementen on kanaal zaken and Open VTB's bericht CloudEvents, made with the suite's
    Open Notificaties client.

    Two abonnementen: sendCloudevents would also turn the zaken notifications into CloudEvents, which OMC drops.
    """

    name: str = "omc-abonnement"
    requires: tuple[str, ...] = ("omc", "opennotificaties")
    wiring: bool = True

    def is_present(self, ctx: Context, /) -> bool:  # noqa: PLR6301  # a Step method
        """Return whether the recorded abonnement exists and its token is not about to expire and has OMC's claims."""
        record = ctx.record(STORE_KEY)
        if not record or float(cast("float", record["expires"])) < time.time() + RENEW_BEFORE:
            return False
        if record.get("issuer_audience") != _issuer_and_audience(ctx.env):
            return False
        if is_reading_openvtb(ctx.env) != bool(record.get("berichten_url")):
            return False
        client = opennotificaties_client(ctx.env)
        urls = [str(record[key]) for key in ("url", "berichten_url") if record.get(key)]
        return all(client.request("GET", url, HTTPStatus.OK, HTTPStatus.NOT_FOUND).ok for url in urls)

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Replace the recorded abonnement with one carrying a fresh token."""
        self.remove(ctx)
        now = time.time()
        callback = ctx.env.profile.urls["omc"] + LISTEN_PATH
        auth = f"Bearer {omc_token(ctx.env, now)}"
        client = opennotificaties_client(ctx.env)
        created = client.post("abonnement", abonnement_body(callback, "zaken", {}, auth=auth))
        record = {"url": created["url"], "expires": now + VALIDITY, "issuer_audience": _issuer_and_audience(ctx.env)}
        if is_reading_openvtb(ctx.env):
            berichten = client.post("abonnement", cloudevent_abonnement_body(callback, BERICHT_EVENTS, auth))
            record["berichten_url"] = berichten["url"]
        return {STORE_KEY: json.dumps(record)}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:  # noqa: PLR6301  # a Step method
        """Delete the recorded abonnement."""
        record = ctx.record(STORE_KEY) or {}
        for key in ("url", "berichten_url"):
            if record.get(key):
                delete_abonnement(opennotificaties_client(ctx.env), str(record[key]))
        return (STORE_KEY,)
