"""Bootstrap step: the suite's own ZGW client in Open Zaak (PLAN.md §4 A1, §11a)."""

from __future__ import annotations

import secrets

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.django_snippets import run_snippet

if TYPE_CHECKING:
    from podiumd_tests.bootstrap import Context

ZGW_CLIENT_ID = "ptest-bootstrap-zgw"
# Key of the client secret in the credentials Secret.
ZGW_STORE_KEY = "ptest_bootstrap_zgw_secret"
# Catalogus of the suite: the client may only touch zaken, documenten and besluiten of zaaktypen in it.
TEST_CATALOGUS_DOMEIN = "PTEST"
TEST_CATALOGUS_RSIN = "000000000"


@dataclass(frozen=True)
class OpenZaakClient:
    """JWT client ptest-bootstrap-zgw, its secret, and the test catalogus PTEST."""

    name: str = "openzaak-client"
    requires: tuple[str, ...] = ("openzaak",)

    def _run(self, ctx: Context, action: str, **extra: object) -> dict[str, object]:
        params: dict[str, object] = {
            "action": action,
            "client_id": ZGW_CLIENT_ID,
            "label": ZGW_CLIENT_ID,
            "domein": TEST_CATALOGUS_DOMEIN,
            "rsin": TEST_CATALOGUS_RSIN,
            **extra,
        }
        return cast("dict[str, object]", run_snippet(ctx.env.kube, "openzaak", "openzaak_client", params))

    def is_present(self, ctx: Context, /) -> bool:
        """Client, secret and catalogus exist, and the secret is in the credentials Secret."""
        status = self._run(ctx, "status")
        stored = ZGW_STORE_KEY in ctx.store.read()
        return bool(status["applicatie"] and status["secret"] and status["catalogus"] and stored)

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Create or replace the client with a new random secret."""
        secret = secrets.token_urlsafe(32)
        self._run(ctx, "apply", secret=secret)
        return {ZGW_STORE_KEY: secret}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Delete the client, its secret and the test catalogus with everything in it."""
        self._run(ctx, "remove")
        return (ZGW_STORE_KEY,)
