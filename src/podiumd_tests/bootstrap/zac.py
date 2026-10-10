"""Wiring: ZAC's automatic ontvangstbevestiging for productaanvragen of the profile's productaanvraag_zaaktype.

The zaakafhandelparameters are the environment's: the step changes them only where the profile
allows it (settings.zac_email_confirmation), leaves a confirmation that is already on as it is,
and on remove puts back the recorded old value, only while the value is still the one it set.
"""

from __future__ import annotations

import json

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.zac import confirmation_on
from podiumd_tests.zac import confirmation_sent
from podiumd_tests.zac import zaakafhandelparameters
from podiumd_tests.zac import zac_session

if TYPE_CHECKING:
    import requests

    from podiumd_tests.bootstrap import Context
    from podiumd_tests.bootstrap.steps import KeycloakUser
    from podiumd_tests.json_data import JsonObject

STORE_KEY = "ptest_bootstrap_zac_email_confirmation_record"
# ZAC's own mail template; GEMEENTE sends from and replies to the environment's municipality address.
WANTED = {"enabled": True, "templateName": "Ontvangstbevestiging", "emailSender": "GEMEENTE", "emailReply": "GEMEENTE"}


@dataclass(frozen=True)
class ZacEmailConfirmation:
    """ZAC's automatic ontvangstbevestiging (automaticEmailConfirmation) for the productaanvraag zaaktype.

    admin: the Keycloak test user that changes ZAC's settings (ZAC's beheerder).
    """

    admin: KeycloakUser
    name: str = "zac-email-confirmation"
    requires: tuple[str, ...] = ("zac", "keycloak")
    wiring: bool = True

    @staticmethod
    def _allowed(ctx: Context) -> str | None:
        """The zaaktype identificatie when the profile allows the change, else None."""
        profile = ctx.env.profile
        return profile.settings.get("productaanvraag_zaaktype") if profile.allows("zac_email_confirmation") else None

    def _session(self, ctx: Context) -> requests.Session:
        return zac_session(ctx.env, self.admin.username, ctx.env.credentials.get(self.admin.store_key))

    @staticmethod
    def _record(ctx: Context) -> dict[str, JsonObject]:
        return cast("dict[str, JsonObject]", json.loads(ctx.store.read().get(STORE_KEY, "{}")))

    def is_present(self, ctx: Context, /) -> bool:
        """Not allowed (nothing to do), or the confirmation is on for every version of the zaaktype."""
        identificatie = self._allowed(ctx)
        if identificatie is None:
            return True
        return confirmation_on(self._session(ctx), ctx.env.profile.urls["zac"], identificatie)

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Switch the confirmation on where it is off; record the old value of what it changed."""
        identificatie = self._allowed(ctx)
        if identificatie is None:
            ctx.notes.append("not allowed: profile setting zac_email_confirmation is off")
            return {}
        http, zac = self._session(ctx), ctx.env.profile.urls["zac"]
        record = self._record(ctx)
        for found in zaakafhandelparameters(http, zac, identificatie):
            uuid = str(section(found, "zaaktype")["uuid"])
            parameters = _parameters(http, zac, uuid)
            old = section(parameters, "automaticEmailConfirmation")
            if confirmation_sent(old):
                continue
            record.setdefault(uuid, old)
            confirmation = {**WANTED, "id": old.get("id")}
            _put(http, zac, {**parameters, "automaticEmailConfirmation": confirmation})
        return {STORE_KEY: json.dumps(record, sort_keys=True)}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Put the recorded old values back, where the confirmation is still the one apply set."""
        record = self._record(ctx)
        if not record:
            return (STORE_KEY,)
        http, zac = self._session(ctx), ctx.env.profile.urls["zac"]
        for uuid, old in record.items():
            response = http.get(f"{zac}/rest/zaakafhandelparameters/{uuid}")
            if response.status_code == HTTPStatus.NOT_FOUND:
                continue
            parameters = cast("JsonObject", expect_status(response, HTTPStatus.OK).json())
            current = section(parameters, "automaticEmailConfirmation")
            if any(current.get(k) != v for k, v in WANTED.items()):
                ctx.notes.append(f"zaaktype {uuid}: automaticEmailConfirmation changed by someone else; left as it is")
                continue
            _put(http, zac, {**parameters, "automaticEmailConfirmation": {**old, "id": current.get("id")}})
        return (STORE_KEY,)


def _parameters(http: requests.Session, zac: str, uuid: str) -> JsonObject:
    """The zaakafhandelparameters of one zaaktype version, complete for a PUT."""
    return cast(
        "JsonObject", expect_status(http.get(f"{zac}/rest/zaakafhandelparameters/{uuid}"), HTTPStatus.OK).json()
    )


def _put(http: requests.Session, zac: str, parameters: JsonObject) -> None:
    expect_status(http.put(f"{zac}/rest/zaakafhandelparameters", json=parameters), HTTPStatus.OK)
