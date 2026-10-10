"""Wiring: KISS's contactmoment kanalen Balie, Telefoon and Internet (KISS Beheer, Kanalen).

Kanalen are runtime data in KISS's database. The step adds only the ones missing, only where the
profile allows it (settings.kiss_kanalen), and on remove deletes only the ones it added.
"""

from __future__ import annotations

import json

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.auth.keycloak import form_login
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries

if TYPE_CHECKING:
    import requests

    from podiumd_tests.bootstrap import Context
    from podiumd_tests.bootstrap.steps import KeycloakUser

STORE_KEY = "ptest_bootstrap_kiss_kanalen_record"
KANALEN = ("Balie", "Telefoon", "Internet")


@dataclass(frozen=True)
class KissKanalen:
    """The kanalen KANALEN in KISS, added by a KISS beheerder.

    admin: the Keycloak test user with KISS's Beheerder role.
    """

    admin: KeycloakUser
    name: str = "kiss-kanalen"
    requires: tuple[str, ...] = ("kiss", "keycloak")
    wiring: bool = True

    @staticmethod
    def _allowed(ctx: Context) -> bool:
        return ctx.env.profile.allows("kiss_kanalen")

    def _session(self, ctx: Context) -> tuple[requests.Session, str]:
        kiss = ctx.env.profile.urls["kiss"]
        http = ctx.env.session()
        form_login(
            http,
            kiss + "/api/challenge?returnUrl=%2F",
            self.admin.username,
            ctx.env.credentials.get(self.admin.store_key),
        )
        return http, kiss

    @staticmethod
    def _current(http: requests.Session, kiss: str) -> dict[str, str]:
        found = get_entries(http, kiss + "/api/KanalenBeheerOverzicht")
        return {str(k["naam"]): str(k["id"]) for k in found}

    def is_present(self, ctx: Context, /) -> bool:
        """Not allowed (nothing to do), or every kanaal of KANALEN exists."""
        if not self._allowed(ctx):
            return True
        return set(KANALEN) <= set(self._current(*self._session(ctx)))

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Add the missing kanalen; record the ones added."""
        if not self._allowed(ctx):
            ctx.notes.append("not allowed: profile setting kiss_kanalen is off")
            return {}
        http, kiss = self._session(ctx)
        added = cast("list[str]", json.loads(ctx.store.read().get(STORE_KEY, "[]")))
        for naam in sorted(set(KANALEN) - set(self._current(http, kiss))):
            expect_status(http.post(kiss + "/api/KanaalToevoegen/", json={"naam": naam}), HTTPStatus.NO_CONTENT)
            added.append(naam)
        return {STORE_KEY: json.dumps(sorted(set(added)))}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Delete the kanalen the step added."""
        added = cast("list[str]", json.loads(ctx.store.read().get(STORE_KEY, "[]")))
        if added:
            http, kiss = self._session(ctx)
            current = self._current(http, kiss)
            for naam in added:
                if naam in current:
                    expect_status(http.delete(f"{kiss}/api/KanaalVerwijderen/{current[naam]}"), HTTPStatus.NO_CONTENT)
        return (STORE_KEY,)
