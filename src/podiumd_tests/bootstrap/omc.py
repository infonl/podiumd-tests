"""Wiring: OMC's abonnement on kanaal zaken, so zaak events reach OMC (TA and ExternalsPodiumD subscribe it by hand).

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
from podiumd_tests.clients.platform import opennotificaties_client
from podiumd_tests.mock_server import mock_server_root
from podiumd_tests.responses import url_host
from podiumd_tests.seed.opennotificaties import delete_abonnement

if TYPE_CHECKING:
    from podiumd_tests.bootstrap import Context
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment

STORE_KEY = "ptest_bootstrap_omc_abonnement_record"
VALIDITY = 365 * 24 * 3600
RENEW_BEFORE = 7 * 24 * 3600


def omc_setting(env: Environment, var: str) -> str:
    """An environment variable of the OMC pod, e.g. NOTIFY_API_BASEURL."""
    return env.kube.exec(env.deployment_for("omc"), "printenv", var).strip()


def notify_mock_missing(env: Environment) -> str | None:
    """Skip reason when OMC's Notify base URL is not the mock server, else None."""
    base = omc_setting(env, "NOTIFY_API_BASEURL")
    if url_host(base) == url_host(mock_server_root(env)):
        return None
    return f"OMC's Notify base URL is {base}, not the mock server {mock_server_root(env)}"


def omc_actor_missing(env: Environment, openklant: ApiClient) -> str | None:
    """Skip reason when Open Klant has no actor OMC_ACTOR_ID, which OMC links to each klantcontact it registers."""
    actor = omc_setting(env, "OMC_ACTOR_ID")
    if openklant.request("GET", f"actoren/{actor}", HTTPStatus.OK, HTTPStatus.NOT_FOUND).ok:
        return None
    return f"Open Klant has no actor {actor} (OMC_ACTOR_ID): the environment owner creates it"


def omc_token(env: Environment, now: float) -> str:
    """A token OMC's Events/Listen and Notify/Confirm accept, valid for VALIDITY from now."""
    payload = {
        "iss": omc_setting(env, "OMC_AUTH_JWT_ISSUER"),
        "aud": omc_setting(env, "OMC_AUTH_JWT_AUDIENCE"),
        "userId": omc_setting(env, "OMC_AUTH_JWT_USERID"),
        "userName": omc_setting(env, "OMC_AUTH_JWT_USERNAME"),
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

    @staticmethod
    def _record(ctx: Context) -> dict[str, object]:
        return cast("dict[str, object]", json.loads(ctx.store.read().get(STORE_KEY, "{}")))

    def is_present(self, ctx: Context, /) -> bool:
        """The recorded abonnement exists and its token is not about to expire."""
        record = self._record(ctx)
        if not record or float(cast("float", record["expires"])) < time.time() + RENEW_BEFORE:
            return False
        return opennotificaties_client(ctx.env).request("GET", str(record["url"]), 200, 404).status_code == 200

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Replace the recorded abonnement with one carrying a fresh token."""
        self.remove(ctx)
        now = time.time()
        body: dict[str, object] = {
            "callbackUrl": ctx.env.profile.urls["omc"] + "/Events/Listen",
            "auth": f"Bearer {omc_token(ctx.env, now)}",
            "kanalen": [{"naam": "zaken", "filters": {}}],
        }
        created = opennotificaties_client(ctx.env).post("abonnement", body)
        return {STORE_KEY: json.dumps({"url": created["url"], "expires": now + VALIDITY})}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Delete the recorded abonnement."""
        record = self._record(ctx)
        if record:
            delete_abonnement(opennotificaties_client(ctx.env), str(record["url"]))
        return (STORE_KEY,)
