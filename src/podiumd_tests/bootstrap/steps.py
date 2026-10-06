"""The bootstrap steps, in the order they are applied (unbootstrap goes in reverse)."""

from __future__ import annotations

import secrets

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.auth.keycloak_admin import KeycloakAdmin
from podiumd_tests.django_snippets import run_snippet

if TYPE_CHECKING:
    from podiumd_tests.bootstrap import Context
    from podiumd_tests.bootstrap import Step

PREFIX = "ptest-bootstrap"
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


@dataclass(frozen=True)
class KeycloakUser:
    """Test user ptest-bootstrap-<key> with a random password, and the wanted roles the realm has.

    The realm comes from settings.keycloak_realm (default podiumd); admin calls go to the
    keycloak-admin URL when the profile has one, with secrets keycloak_admin_username/password.
    """

    key: str
    realm_roles: tuple[str, ...] = ()
    client_roles: tuple[tuple[str, str], ...] = ()
    groups: tuple[str, ...] = ()
    attributes: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    requires: tuple[str, ...] = ("keycloak",)

    @property
    def name(self) -> str:
        """Step name."""
        return f"keycloak-user-{self.key}"

    @property
    def username(self) -> str:
        """The user's name in Keycloak."""
        return f"{PREFIX}-{self.key}"

    @property
    def store_key(self) -> str:
        """Key of the password in the credentials Secret."""
        return keycloak_password_key(self.key)

    def _admin(self, ctx: Context) -> KeycloakAdmin:
        env = ctx.env
        url = env.profile.urls.get("keycloak-admin") or env.profile.urls["keycloak"]
        realm = env.profile.settings.get("keycloak_realm", "podiumd")
        admin = (env.credentials.get("keycloak_admin_username"), env.credentials.get("keycloak_admin_password"))
        return KeycloakAdmin(env.session(), url, realm, admin)

    def is_present(self, ctx: Context, /) -> bool:
        """The user exists, and its password is in the credentials Secret."""
        return self._admin(ctx).user_id(self.username) is not None and self.store_key in ctx.store.read()

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Recreate the user with a new password and the wanted roles and groups that exist."""
        admin = self._admin(ctx)
        old = admin.user_id(self.username)
        if old:
            admin.delete_user(old)
        password = secrets.token_hex(20)
        user = admin.create_user(self.username, password, self.attributes)
        realm_roles = admin.realm_roles(self.realm_roles)
        admin.add_realm_roles(user, realm_roles)
        missing = sorted(set(self.realm_roles) - {str(r["name"]) for r in realm_roles})
        for client, role in self.client_roles:
            found = admin.client_role(client, role)
            if found:
                admin.add_client_role(user, *found)
            else:
                missing.append(f"{client}:{role}")
        for group in self.groups:
            group_id = admin.group_id(group)
            if group_id:
                admin.join_group(user, group_id)
            else:
                missing.append(f"group {group}")
        if missing:
            ctx.notes.append("not in realm: " + ", ".join(missing))
        return {self.store_key: password}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Delete the user."""
        admin = self._admin(ctx)
        user = admin.user_id(self.username)
        if user:
            admin.delete_user(user)
        return (self.store_key,)


def keycloak_password_key(key: str) -> str:
    """Key of a test user's password in the credentials Secret."""
    return f"{PREFIX.replace('-', '_')}_{key}_password"


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
    # Users for KISS and ITA (TA kcc-medewerker), for the admin UIs, PABC and ZAC (TA testadmin),
    # and for the DigiD and eHerkenning logins through Keycloak (TA testinwoner, testinwoner2, testbedrijf).
    KeycloakUser(
        "kcc",
        realm_roles=("Klantcontactmedewerker",),
        client_roles=(("kiss", "Klantcontactmedewerker"), ("ita", "ITA_Gebruiker")),
    ),
    KeycloakUser(
        "admin",
        realm_roles=("Registreerders", "Behandelaar", "Coordinator", "Functioneel-beheerder", "beheerder_elk_domein"),
        client_roles=(("pabc", "administrator"),),
        groups=("beheerders-elk-domein",),
    ),
    KeycloakUser("inwoner", attributes={"bsn": ["999990019"]}),
    KeycloakUser("inwoner2", attributes={"bsn": ["999990038"]}),
    KeycloakUser("bedrijf", attributes={"kvk": ["68750110"], "vestigingsnummer": ["000038509564"]}),
)
