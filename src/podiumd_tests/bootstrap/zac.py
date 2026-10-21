"""Wiring: parts of ZAC's zaakafhandelparameters of the profile's productaanvraag_zaaktype that tests need.

The zaakafhandelparameters are the environment's: a step changes its part only where the profile
allows it (an opt-in setting), leaves a part that is already on as it is, and on remove puts back
the recorded old value, only while the value is still the one it set.
"""

from __future__ import annotations

import json

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.bootstrap.names import PREFIX
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.zac import confirmation_sent
from podiumd_tests.zac import zaakafhandelparameters
from podiumd_tests.zac import zac_session

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.bootstrap import Context
    from podiumd_tests.bootstrap.keycloak import KeycloakUser
    from podiumd_tests.json_data import JsonObject


@dataclass(frozen=True)
class ZacPart:
    """A field of the zaakafhandelparameters, or the humanTaskParameters item of one plan item.

    wanted: the values apply sets; is_on: whether a value counts as on, so apply leaves it.
    """

    key: str
    wanted: JsonObject
    is_on: Callable[[JsonObject], bool]
    plan_item: str | None = None

    def read(self, parameters: JsonObject) -> JsonObject:
        """The part's current value."""
        if self.plan_item is None:
            return section(parameters, self.key)
        items = entries(parameters.get(self.key))
        empty: JsonObject = {}
        return next((i for i in items if section(i, "planItemDefinition").get("id") == self.plan_item), empty)

    def write(self, parameters: JsonObject, value: JsonObject) -> JsonObject:
        """The parameters with the part set to value."""
        if self.plan_item is None:
            return {**parameters, self.key: value}
        items = entries(parameters.get(self.key))
        mine = [value if section(i, "planItemDefinition").get("id") == self.plan_item else i for i in items]
        return {**parameters, self.key: mine}

    def is_mine(self, value: JsonObject) -> bool:
        """The value still has what apply set."""
        return all(value.get(k) == v for k, v in self.wanted.items())


# ZAC's own mail template; GEMEENTE sends from and replies to the environment's municipality address.
EMAIL_CONFIRMATION = ZacPart(
    "automaticEmailConfirmation",
    {"enabled": True, "templateName": "Ontvangstbevestiging", "emailSender": "GEMEENTE", "emailReply": "GEMEENTE"},
    confirmation_sent,
)
# ZAC's default leaves every human task inactive, so no task can be started on a zaak.
AANVULLENDE_INFORMATIE = ZacPart(
    "humanTaskParameters", {"actief": True}, lambda item: bool(item.get("actief")), "AANVULLENDE_INFORMATIE"
)


@dataclass(frozen=True)
class ZacParameters:
    """A part of the zaakafhandelparameters of every version of the productaanvraag zaaktype.

    admin: the Keycloak test user that changes ZAC's settings (ZAC's beheerder);
    setting: the profile's opt-in setting that allows the change.
    """

    admin: KeycloakUser
    name: str
    setting: str
    part: ZacPart
    requires: tuple[str, ...] = ("zac", "keycloak")
    wiring: bool = True

    @property
    def store_key(self) -> str:
        """Key of the record of old values in the credentials Secret."""
        return f"{PREFIX.replace('-', '_')}_{self.name.replace('-', '_')}_record"

    def _allowed(self, ctx: Context) -> str | None:
        """The zaaktype identificatie when the profile allows the change, else None."""
        profile = ctx.env.profile
        return profile.settings.get("productaanvraag_zaaktype") if profile.allows(self.setting) else None

    def not_allowed(self, ctx: Context) -> str | None:
        """Why the profile does not allow the change, or None."""
        if self._allowed(ctx) is None:
            return f"profile setting {self.setting} is off for {ctx.env.profile.name}"
        return None

    def _session(self, ctx: Context) -> requests.Session:
        return zac_session(ctx.env, self.admin.username, ctx.env.credentials.get(self.admin.store_key))

    def _record(self, ctx: Context) -> dict[str, JsonObject]:
        return cast("dict[str, JsonObject]", json.loads(ctx.store.read().get(self.store_key, "{}")))

    def is_present(self, ctx: Context, /) -> bool:
        """Not allowed (nothing to do), or the part is on for every version of the zaaktype."""
        identificatie = self._allowed(ctx)
        if identificatie is None:
            return True
        http, zac = self._session(ctx), ctx.env.profile.urls["zac"]
        versions = zaakafhandelparameters(http, zac, identificatie)
        return bool(versions) and all(
            self.part.is_on(self.part.read(_parameters(http, zac, str(section(v, "zaaktype")["uuid"]))))
            for v in versions
        )

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Switch the part on where it is off; record the old value of what it changed."""
        identificatie = self._allowed(ctx)
        if identificatie is None:
            ctx.notes.append(f"not allowed: profile setting {self.setting} is off")
            return {}
        http, zac = self._session(ctx), ctx.env.profile.urls["zac"]
        record = self._record(ctx)
        versions = zaakafhandelparameters(http, zac, identificatie)
        if not versions:
            msg = f"ZAC has no zaakafhandelparameters for zaaktype {identificatie}: the environment owner sets them"
            raise LookupError(msg)
        for found in versions:
            uuid = str(section(found, "zaaktype")["uuid"])
            parameters = _parameters(http, zac, uuid)
            old = self.part.read(parameters)
            if self.part.is_on(old):
                continue
            record.setdefault(uuid, old)
            _put(http, zac, self.part.write(parameters, {**old, **self.part.wanted}))
        return {self.store_key: json.dumps(record, sort_keys=True)}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Put the recorded old values back, where the part is still the one apply set."""
        record = self._record(ctx)
        if not record:
            return (self.store_key,)
        http, zac = self._session(ctx), ctx.env.profile.urls["zac"]
        for uuid, old in record.items():
            response = http.get(f"{zac}/rest/zaakafhandelparameters/{uuid}")
            if response.status_code == HTTPStatus.NOT_FOUND:
                continue
            parameters = cast("JsonObject", expect_status(response, HTTPStatus.OK).json())
            current = self.part.read(parameters)
            if not self.part.is_mine(current):
                ctx.notes.append(f"zaaktype {uuid}: {self.part.key} changed by someone else; left as it is")
                continue
            _put(http, zac, self.part.write(parameters, {**old, "id": current.get("id")}))
        return (self.store_key,)


def _parameters(http: requests.Session, zac: str, uuid: str) -> JsonObject:
    """The zaakafhandelparameters of one zaaktype version, complete for a PUT."""
    return cast(
        "JsonObject", expect_status(http.get(f"{zac}/rest/zaakafhandelparameters/{uuid}"), HTTPStatus.OK).json()
    )


def _put(http: requests.Session, zac: str, parameters: JsonObject) -> None:
    expect_status(http.put(f"{zac}/rest/zaakafhandelparameters", json=parameters), HTTPStatus.OK)
