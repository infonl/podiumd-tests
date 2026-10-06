"""The bootstrap steps, in the order they are applied (unbootstrap goes in reverse)."""

from __future__ import annotations

import secrets

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.django_snippets import run_snippet

if TYPE_CHECKING:
    from podiumd_tests.bootstrap import Context
    from podiumd_tests.bootstrap import Step

# The suite's own ZGW client in Open Zaak, and its test catalogus: the client may only touch
# zaken, documenten and besluiten of zaaktypen in that catalogus (PLAN.md §11a).
ZGW_CLIENT_ID = "ptest-bootstrap-zgw"
ZGW_STORE_KEY = "ptest_bootstrap_zgw_secret"
TEST_CATALOGUS_DOMEIN = "PTEST"
TEST_CATALOGUS_RSIN = "000000000"
# The suite's client in Open Notificaties: publishes and subscribes.
NRC_CLIENT_ID = "ptest-bootstrap-nrc"
NRC_STORE_KEY = "ptest_bootstrap_nrc_secret"
# API tokens (TokenAuth identifier = store key).
OPENKLANT_STORE_KEY = "ptest_bootstrap_openklant_token"
OBJECTTYPEN_STORE_KEY = "ptest_bootstrap_objecttypen_token"


@dataclass(frozen=True)
class SnippetStep:
    """A step done by one Django snippet with actions status, apply and remove, and one random secret.

    The secret is generated here, sent to the snippet over stdin, and stored under store_key.
    """

    name: str
    component: str
    snippet: str
    store_key: str
    params: dict[str, object] = field(default_factory=dict[str, object])

    @property
    def requires(self) -> tuple[str, ...]:
        """The component the snippet runs in."""
        return (self.component,)

    def _run(self, ctx: Context, action: str, **extra: object) -> dict[str, object]:
        deployment = ctx.env.deployment_for(self.component)
        params = {**self.params, "action": action, **extra}
        return cast("dict[str, object]", run_snippet(ctx.env.kube, deployment, self.snippet, params))

    def is_present(self, ctx: Context, /) -> bool:
        """The objects exist, and the secret is in the credentials Secret."""
        return bool(self._run(ctx, "status")["present"]) and self.store_key in ctx.store.read()

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Create or replace the objects with a new random secret."""
        secret = secrets.token_hex(20)  # 40 characters: the longest TokenAuth.token allows
        self._run(ctx, "apply", secret=secret)
        return {self.store_key: secret}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Delete the objects."""
        self._run(ctx, "remove")
        return (self.store_key,)


def token_step(component: str, module: str, store_key: str) -> SnippetStep:
    """A TokenAuth step; the token's identifier is its store key."""
    params: dict[str, object] = {"module": module, "identifier": store_key}
    return SnippetStep(f"{component}-token", component, "token_auth", store_key, params)


STEPS: tuple[Step, ...] = (
    SnippetStep(
        "openzaak-client",
        "openzaak",
        "openzaak_client",
        ZGW_STORE_KEY,
        {
            "client_id": ZGW_CLIENT_ID,
            "label": ZGW_CLIENT_ID,
            "domein": TEST_CATALOGUS_DOMEIN,
            "rsin": TEST_CATALOGUS_RSIN,
        },
    ),
    SnippetStep(
        "opennotificaties-client",
        "opennotificaties",
        "zgw_client",
        NRC_STORE_KEY,
        {"client_id": NRC_CLIENT_ID, "scopes": {"nrc": ["notificaties.consumeren", "notificaties.publiceren"]}},
    ),
    token_step("openklant", "openklant.components.token.models", OPENKLANT_STORE_KEY),
    token_step("objecttypen", "objecttypes.token.models", OBJECTTYPEN_STORE_KEY),
)
