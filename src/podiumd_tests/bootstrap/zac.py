"""Wiring: parts of ZAC's zaakafhandelparameters of the profile's productaanvraag_zaaktype that tests need.

The zaakafhandelparameters are the environment's: a step changes its part only where the profile
allows it (an opt-in setting), leaves a part that is already on as it is, and on remove puts back
the recorded old value, only while the value is still the one it set.
"""

from __future__ import annotations

import json

from dataclasses import dataclass
from dataclasses import field
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast
from typing import override

from podiumd_tests.bootstrap.names import PREFIX
from podiumd_tests.bootstrap.snippet_step import SnippetStep
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.zac import clear_ztc_cache
from podiumd_tests.zac import is_confirmation_sent
from podiumd_tests.zac import read_zaakafhandelparameters
from podiumd_tests.zac import save_zaakafhandelparameters
from podiumd_tests.zac import zaakafhandelparameters
from podiumd_tests.zac import zac_session

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.bootstrap.keycloak import KeycloakUser
    from podiumd_tests.bootstrap.runner import Context
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
        """Return the part's current value."""
        if self.plan_item is None:
            return section(parameters, self.key)
        items = entries(parameters.get(self.key))
        empty: JsonObject = {}
        return next((item for item in items if section(item, "planItemDefinition").get("id") == self.plan_item), empty)

    def write(self, parameters: JsonObject, value: JsonObject) -> JsonObject:
        """Return the parameters with the part set to value."""
        if self.plan_item is None:
            return {**parameters, self.key: value}
        items = entries(parameters.get(self.key))
        mine = [value if section(item, "planItemDefinition").get("id") == self.plan_item else item for item in items]
        return {**parameters, self.key: mine}

    def is_mine(self, value: JsonObject) -> bool:
        """Return whether the value still has what apply set."""
        return all(value.get(key) == wanted for key, wanted in self.wanted.items())


# ZAC's own mail template; GEMEENTE sends from and replies to the environment's municipality address.
EMAIL_CONFIRMATION = ZacPart(
    "automaticEmailConfirmation",
    {"enabled": True, "templateName": "Ontvangstbevestiging", "emailSender": "GEMEENTE", "emailReply": "GEMEENTE"},
    is_confirmation_sent,
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

    def not_allowed(self, ctx: Context) -> str | None:
        """Why the profile does not allow the change, or None."""
        if self._allowed(ctx) is None:
            return f"profile setting {self.setting} is off for {ctx.env.profile.name}"
        return None

    def is_present(self, ctx: Context, /) -> bool:
        """Not allowed (nothing to do), or the part is on for every version of the zaaktype."""
        identificatie = self._allowed(ctx)
        if identificatie is None:
            return True
        http, zac = self._session(ctx), ctx.env.profile.urls["zac"]
        versions = zaakafhandelparameters(http, zac, identificatie)
        for version in versions:
            uuid = str(section(version, "zaaktype")["uuid"])
            if not self.part.is_on(self.part.read(read_zaakafhandelparameters(http, zac, uuid))):
                return False
        return bool(versions)

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
            parameters = read_zaakafhandelparameters(http, zac, uuid)
            old = self.part.read(parameters)
            if self.part.is_on(old):
                continue
            record.setdefault(uuid, old)
            save_zaakafhandelparameters(http, zac, self.part.write(parameters, {**old, **self.part.wanted}))
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
            save_zaakafhandelparameters(http, zac, self.part.write(parameters, {**old, "id": current.get("id")}))
        return (self.store_key,)

    def _allowed(self, ctx: Context) -> str | None:
        """Return the zaaktype identificatie when the profile allows the change, else None."""
        profile = ctx.env.profile
        return profile.settings.get("productaanvraag_zaaktype") if profile.is_allowed(self.setting) else None

    def _session(self, ctx: Context) -> requests.Session:
        return zac_session(ctx.env, self.admin.username, ctx.env.credentials.get(self.admin.store_key))

    def _record(self, ctx: Context) -> dict[str, JsonObject]:
        return cast("dict[str, JsonObject]", json.loads(ctx.store.read().get(self.store_key, "{}")))


@dataclass(frozen=True)
class ZacCatalogusStep(SnippetStep):
    """A SnippetStep on Open Zaak's catalogi that ZAC reads; it then clears ZAC's ZTC cache.

    ZAC caches catalogus types for an hour, and a snippet's change sends no notification.
    """

    # The Keycloak test user that clears the cache (ZAC's beheerder).
    admin: KeycloakUser = field(kw_only=True)

    @override
    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Apply the snippet, then clear ZAC's cache."""
        applied = super().apply(ctx)
        self._clear(ctx)
        return applied

    @override
    def ensure(self, ctx: Context, /) -> dict[str, str] | None:
        """Ensure the snippet's objects; clear ZAC's cache when it applied."""
        applied = super().ensure(ctx)
        if applied is not None:
            self._clear(ctx)
        return applied

    @override
    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Remove the snippet's objects, then clear ZAC's cache."""
        removed = super().remove(ctx)
        self._clear(ctx)
        return removed

    def _clear(self, ctx: Context) -> None:
        session = zac_session(ctx.env, self.admin.username, ctx.env.credentials.get(self.admin.store_key))
        clear_ztc_cache(session, ctx.env.profile.urls["zac"])
