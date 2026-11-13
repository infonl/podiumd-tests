"""OMC's taak objecttype, and wiring: OMC's abonnement on kanaal zaken, so zaak events reach OMC (TA and
ExternalsPodiumD subscribe it by hand).

The abonnement's auth is a token OMC accepts: HS256 with OMC's own secret and its issuer,
audience and user claims, all read from the OMC pod. It expires after VALIDITY; the step then
reports itself missing and bootstrap renews it.
"""

from __future__ import annotations

import json
import time

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.auth.zgw_jwt import hs256_jwt
from podiumd_tests.bootstrap.names import TAAK_OBJECTTYPE
from podiumd_tests.bootstrap.names import TAAK_OBJECTTYPE_UUID
from podiumd_tests.bootstrap.snippet_step import SnippetStep
from podiumd_tests.clients.platform import opennotificaties_client
from podiumd_tests.mock_server import mock_server_root
from podiumd_tests.responses import url_host
from podiumd_tests.seed.opennotificaties import abonnement_body
from podiumd_tests.seed.opennotificaties import delete_abonnement

if TYPE_CHECKING:
    from podiumd_tests.bootstrap.runner import Context
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment

STORE_KEY = "ptest_bootstrap_omc_abonnement_record"
VALIDITY = 365 * 24 * 3600
RENEW_BEFORE = 7 * 24 * 3600
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
OMC_TAAK_OBJECTTYPE = SnippetStep(
    "objecttypen-taak",
    ("objecttypen", "objecten", "omc"),
    "objecttypen_published",
    None,
    {"name": TAAK_OBJECTTYPE, "uuid": TAAK_OBJECTTYPE_UUID, "schema": TAAK_SCHEMA},
    opt_in="omc_taak_objecttype",
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


@dataclass(frozen=True)
class OmcAbonnement:
    """An abonnement of OMC's Events/Listen on kanaal zaken, made with the suite's Open Notificaties client."""

    name: str = "omc-abonnement"
    requires: tuple[str, ...] = ("omc", "opennotificaties")
    wiring: bool = True

    def is_present(self, ctx: Context, /) -> bool:  # noqa: PLR6301  # a Step method
        """Return whether the recorded abonnement exists and its token is not about to expire."""
        record = ctx.record(STORE_KEY)
        if not record or float(cast("float", record["expires"])) < time.time() + RENEW_BEFORE:
            return False
        response = opennotificaties_client(ctx.env).request(
            "GET", str(record["url"]), HTTPStatus.OK, HTTPStatus.NOT_FOUND
        )
        return response.status_code == HTTPStatus.OK

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Replace the recorded abonnement with one carrying a fresh token."""
        self.remove(ctx)
        now = time.time()
        callback = f"{ctx.env.profile.urls['omc']}/Events/Listen"
        body = abonnement_body(callback, "zaken", {}, auth=f"Bearer {omc_token(ctx.env, now)}")
        created = opennotificaties_client(ctx.env).post("abonnement", body)
        return {STORE_KEY: json.dumps({"url": created["url"], "expires": now + VALIDITY})}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:  # noqa: PLR6301  # a Step method
        """Delete the recorded abonnement."""
        record = ctx.record(STORE_KEY)
        if record:
            delete_abonnement(opennotificaties_client(ctx.env), str(record["url"]))
        return (STORE_KEY,)
