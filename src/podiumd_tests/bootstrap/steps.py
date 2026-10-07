"""The bootstrap steps, in the order they are applied (unbootstrap goes in reverse)."""

from __future__ import annotations

import json
import secrets

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.auth.keycloak_admin import KeycloakAdmin
from podiumd_tests.django_snippets import run_snippet

if TYPE_CHECKING:
    from collections.abc import Callable

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
# Test zaaktype and informatieobjecttype in the test catalogus (TA TEST-FORMULIER), and the
# Open Formulieren test form that registers zaken on it (TA poc-klacht-test).
TEST_ZAAKTYPE = "ptest-bootstrap-klacht"
TEST_IOT = "ptest-bootstrap-bijlage"
TEST_FORM = "ptest-bootstrap-klacht"
# Open Notificaties kanalen the ported tests use (TA seed-notificaties.sh), with their filters.
KANALEN = {
    "zaken": ["bronorganisatie", "zaaktype", "vertrouwelijkheidaanduiding"],
    "statussen": ["bronorganisatie", "zaaktype", "vertrouwelijkheidaanduiding"],
    "documenten": ["bronorganisatie", "informatieobjecttype", "vertrouwelijkheidaanduiding"],
    "partijen": ["nummer", "soort_partij"],
    "internetaken": ["nummer", "gevraagde_handeling", "toelichting", "status"],
}
# API tokens (TokenAuth identifier = store key).
OPENKLANT_STORE_KEY = "ptest_bootstrap_openklant_token"
OBJECTTYPEN_STORE_KEY = "ptest_bootstrap_objecttypen_token"


@dataclass(frozen=True)
class SnippetStep:  # pylint: disable=too-many-instance-attributes  # a declarative step definition
    """A step done by one Django snippet with actions status, apply and remove.

    Secret mode (default): a random secret is generated here, sent to the snippet and stored
    under store_key. Record mode (record=True), for wiring that adds to shared objects: apply
    gets the stored record and returns it extended with what it added; remove gets it back
    and undoes exactly that. Without store_key the step stores nothing.
    """

    name: str
    # The first component is the one the snippet runs in.
    requires: tuple[str, ...]
    snippet: str
    store_key: str | None
    params: dict[str, object] = field(default_factory=dict[str, object])
    record: bool = False
    wiring: bool = False
    # Parameters known only at run time, e.g. a stored secret or an in-cluster URL.
    context_params: Callable[[Context], dict[str, object]] | None = None

    def _run(self, ctx: Context, action: str, **extra: object) -> dict[str, object]:
        deployment = ctx.env.deployment_for(self.requires[0])
        runtime = self.context_params(ctx) if self.context_params else {}
        params = {**self.params, **runtime, "action": action, **extra}
        return cast("dict[str, object]", run_snippet(ctx.env.kube, deployment, self.snippet, params))

    def is_present(self, ctx: Context, /) -> bool:
        """The objects exist, and what the step stores is in the credentials Secret."""
        stored = self.store_key is None or self.store_key in ctx.store.read()
        return bool(self._run(ctx, "status")["present"]) and stored

    def _stored_record(self, ctx: Context) -> object:
        return json.loads(ctx.store.read().get(self.store_key or "", "{}"))

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Create the objects: with a new random secret, or extending the stored record."""
        if self.store_key is None:
            self._run(ctx, "apply")
            return {}
        if self.record:
            result = self._run(ctx, "apply", record=self._stored_record(ctx))
            return {self.store_key: json.dumps(result["record"], sort_keys=True)}
        secret = secrets.token_hex(20)  # 40 characters: the longest TokenAuth.token allows
        self._run(ctx, "apply", secret=secret)
        return {self.store_key: secret}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Delete the objects, or undo what the stored record lists."""
        self._run(ctx, "remove", **({"record": self._stored_record(ctx)} if self.record else {}))
        return () if self.store_key is None else (self.store_key,)


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
    wiring: bool = False

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


def openformulieren_params(ctx: Context) -> dict[str, object]:
    """The ZGW client secret, and Open Zaak's URL as Open Formulieren reaches it in the cluster."""
    env = ctx.env
    default = f"http://{env.deployment_for('openzaak')}.{env.profile.kube.namespace}"
    return {
        "secret": ctx.store.read().get(ZGW_STORE_KEY, ""),  # empty only before openzaak-client ran
        "openzaak_url": env.profile.settings.get("openzaak_internal_url", default),
    }


def token_step(component: str, module: str, store_key: str) -> SnippetStep:
    """A TokenAuth step; the token's identifier is its store key."""
    params: dict[str, object] = {"module": module, "identifier": store_key}
    return SnippetStep(f"{component}-token", (component,), "token_auth", store_key, params)


STEPS: tuple[Step, ...] = (
    SnippetStep(
        "openzaak-client",
        ("openzaak",),
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
        ("opennotificaties",),
        "zgw_client",
        NRC_STORE_KEY,
        {"client_id": NRC_CLIENT_ID, "scopes": {"nrc": ["notificaties.consumeren", "notificaties.publiceren"]}},
    ),
    token_step("openklant", "openklant.components.token.models", OPENKLANT_STORE_KEY),
    token_step("objecttypen", "objecttypes.token.models", OBJECTTYPEN_STORE_KEY),
    SnippetStep(
        "openzaak-zaaktype",
        ("openzaak",),
        "openzaak_zaaktype",
        None,
        {
            "domein": TEST_CATALOGUS_DOMEIN,
            "rsin": TEST_CATALOGUS_RSIN,
            "identificatie": TEST_ZAAKTYPE,
            "iot_omschrijving": TEST_IOT,
        },
    ),
    # Platform wiring (PLAN.md §4 A2).
    SnippetStep(
        "openzaak-of-autorisatie",
        ("openzaak", "openformulieren"),
        "catalogus_autorisatie",
        "ptest_bootstrap_of_autorisatie_record",
        {"domein": TEST_CATALOGUS_DOMEIN, "rsin": TEST_CATALOGUS_RSIN},
        record=True,
        wiring=True,
        context_params=lambda ctx: {
            "client_id": ctx.env.profile.settings.get("openformulieren_zgw_client_id", "open-formulieren")
        },
    ),
    SnippetStep(
        "openformulieren-form",
        ("openformulieren", "openzaak"),
        "openformulieren_form",
        None,
        {
            "prefix": PREFIX,
            "form_slug": TEST_FORM,
            "client_id": ZGW_CLIENT_ID,
            "domein": TEST_CATALOGUS_DOMEIN,
            "rsin": TEST_CATALOGUS_RSIN,
            "zaaktype": TEST_ZAAKTYPE,
            "informatieobjecttype": TEST_IOT,
        },
        wiring=True,
        context_params=openformulieren_params,
    ),
    SnippetStep(
        "opennotificaties-kanalen",
        ("opennotificaties",),
        "kanalen",
        "ptest_bootstrap_kanalen_record",
        {"kanalen": KANALEN},
        record=True,
        wiring=True,
    ),
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
