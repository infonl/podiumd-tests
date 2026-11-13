"""Wiring: Open Inwoner's abonnement on kanaal zaken, so the portal mails the burger about a zaak (opt-in).

Open Inwoner's webhook accepts a call whose token carries the client_id of one of its Subscriptions and
is signed with that Subscription's secret. Open Notificaties tests the callback when the abonnement is
made, so the Subscription comes first.
"""

from __future__ import annotations

import json
import secrets

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.auth.zgw_jwt import zgw_jwt
from podiumd_tests.bootstrap.names import PREFIX
from podiumd_tests.clients.platform import opennotificaties_client
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.json_data import entries
from podiumd_tests.seed.opennotificaties import abonnement_body
from podiumd_tests.seed.opennotificaties import delete_abonnement

if TYPE_CHECKING:
    from podiumd_tests.bootstrap.runner import Context
    from podiumd_tests.environment import Environment

SETTING = "oi_notifications"
STORE_KEY = "ptest_bootstrap_openinwoner_notifications_record"
CLIENT_ID = f"{PREFIX}-openinwoner"
WEBHOOK = "/api/openzaak/notifications/webhook/zaken"


def oi_notifications_missing(env: Environment) -> str | None:
    """Skip reason when Open Notificaties does not call Open Inwoner's webhook on kanaal zaken, else None."""
    abonnementen = opennotificaties_client(env).list("abonnement", {})
    calls_oi = any(
        str(abonnement.get("callbackUrl", "")).endswith(WEBHOOK)
        and any(kanaal.get("naam") == "zaken" for kanaal in entries(abonnement.get("kanalen")))
        for abonnement in abonnementen
    )
    if calls_oi and _is_wired(env):
        return None
    return (
        f"Open Inwoner gets no zaken notifications on {env.profile.name}: the environment owner subscribes it, "
        f"or set profile setting {SETTING} and run bootstrap step openinwoner-notifications"
    )


@dataclass(frozen=True)
class OiNotifications:
    """Open Inwoner's Subscription and its abonnement in Open Notificaties, where profile setting SETTING allows it."""

    name: str = "openinwoner-notifications"
    requires: tuple[str, ...] = ("openinwoner", "opennotificaties")
    wiring: bool = True

    def is_present(self, ctx: Context, /) -> bool:  # noqa: PLR6301  # a Step method
        """Not allowed (nothing to do), or the recorded abonnement and the Subscription exist."""
        if not ctx.env.profile.is_allowed(SETTING):
            return True
        record = ctx.record(STORE_KEY)
        if not record:
            return False
        response = opennotificaties_client(ctx.env).request(
            "GET", str(record["abonnement"]), HTTPStatus.OK, HTTPStatus.NOT_FOUND
        )
        return response.status_code == HTTPStatus.OK and bool(_snippet(ctx, "status")["present"])

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Replace the recorded Subscription and abonnement with new ones sharing a fresh secret."""
        self.remove(ctx)
        if not ctx.env.profile.is_allowed(SETTING):
            ctx.notes.append(f"not allowed: profile setting {SETTING} is off")
            return {}
        secret = secrets.token_hex(20)
        callback = f"{ctx.env.profile.urls['openinwoner']}{WEBHOOK}"
        nrc_url = f"{ctx.env.profile.urls['opennotificaties']}/api/v1/"
        oi_record = _snippet(ctx, "apply", secret=secret, callback_url=callback, nrc_url=nrc_url)["record"]
        body = abonnement_body(callback, "zaken", {}, auth=f"Bearer {zgw_jwt(CLIENT_ID, secret)}")
        try:
            created = opennotificaties_client(ctx.env).post("abonnement", body)
        except Exception:
            _snippet(ctx, "remove", record=oi_record)
            raise
        return {STORE_KEY: json.dumps({**cast("dict[str, object]", oi_record), "abonnement": created["url"]})}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:  # noqa: PLR6301  # a Step method
        """Delete the recorded abonnement, then the Subscription and the NotificationsAPIConfig apply created."""
        record = ctx.record(STORE_KEY)
        if record:
            delete_abonnement(opennotificaties_client(ctx.env), str(record["abonnement"]))
            _snippet(ctx, "remove", record=record)
        return (STORE_KEY,)


def _snippet(ctx: Context, action: str, **params: object) -> dict[str, object]:
    params = {"action": action, "client_id": CLIENT_ID, **params}
    deployment = ctx.env.deployment_for("openinwoner")
    return cast("dict[str, object]", run_snippet(ctx.env.kube, deployment, "oi_notifications", params))


def _is_wired(env: Environment) -> bool:
    found = run_snippet(env.kube, env.deployment_for("openinwoner"), "oi_notifications", {"action": "wired"})
    return bool(cast("dict[str, object]", found)["present"])
