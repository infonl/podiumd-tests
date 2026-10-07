"""The bootstrap steps, in the order they are applied (unbootstrap goes in reverse)."""

from __future__ import annotations

import json
import secrets

from dataclasses import dataclass
from dataclasses import field
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.auth.keycloak_admin import user_email
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status
from podiumd_tests.webhook import WebhookReceiver

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.bootstrap import Context
    from podiumd_tests.bootstrap import Step

PREFIX = "ptest-bootstrap"
# The suite's own ZGW client in Open Zaak, and its test catalogus: the client may only touch
# zaken, documenten and besluiten of zaaktypen in that catalogus (PLAN.md §11a).
ZGW_CLIENT_ID = "ptest-bootstrap-zgw"
ZGW_STORE_KEY = "ptest_bootstrap_zgw_secret"
ZGW_OPENBAAR_CLIENT_ID = "ptest-bootstrap-zgw-openbaar"
ZGW_OPENBAAR_STORE_KEY = "ptest_bootstrap_zgw_openbaar_secret"
ZGW_NOAUTH_CLIENT_ID = "ptest-bootstrap-zgw-noauth"
ZGW_NOAUTH_STORE_KEY = "ptest_bootstrap_zgw_noauth_secret"
# Scope prefixes per component on the test catalogus, and the Catalogi API scopes.
ZGW_COMPONENTS: dict[str, tuple[str, ...]] = {
    "zrc": ("zaken.", "audittrails."),
    "drc": ("documenten.", "audittrails."),
    "brc": ("besluiten.", "audittrails."),
}
CATALOGI_SCOPES = ("catalogi.lezen", "catalogi.schrijven")
TEST_CATALOGUS_DOMEIN = "PTEST"
TEST_CATALOGUS_RSIN = "000000000"
# The suite's client in Open Notificaties: publishes and subscribes.
NRC_CLIENT_ID = "ptest-bootstrap-nrc"
NRC_STORE_KEY = "ptest_bootstrap_nrc_secret"
# Test zaaktype and informatieobjecttype in the test catalogus (TA TEST-FORMULIER), and the
# Open Formulieren test form that registers zaken on it (TA poc-klacht-test).
TEST_ZAAKTYPE = "ptest-bootstrap-klacht"
TEST_IOT = "ptest-bootstrap-bijlage"
TEST_BESLUITTYPE = "ptest-bootstrap-besluit"
TEST_FORM = "ptest-bootstrap-klacht"
# Open Notificaties kanalen the ported tests use, with the filters of ExternalsPodiumD and podiumd-infra
# (statussen: TA seed-notificaties.sh only).
KANALEN = {
    "zaken": ["bronorganisatie", "zaaktype", "vertrouwelijkheidaanduiding"],
    "statussen": ["bronorganisatie", "zaaktype", "vertrouwelijkheidaanduiding"],
    "documenten": ["bronorganisatie", "informatieobjecttype", "vertrouwelijkheidaanduiding"],
    "partijen": ["nummer", "interne_notitie", "soort_partij"],
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
            self._apply(ctx)
            return {}
        if self.record:
            result = self._apply(ctx, record=self._stored_record(ctx))
            return {self.store_key: json.dumps(result["record"], sort_keys=True)}
        secret = secrets.token_hex(20)  # 40 characters: the longest TokenAuth.token allows
        self._apply(ctx, secret=secret)
        return {self.store_key: secret}

    def _apply(self, ctx: Context, **extra: object) -> dict[str, object]:
        """Run apply; the snippet's "notes" go to the step's outcome."""
        result = self._run(ctx, "apply", **extra)
        ctx.notes.extend(str(n) for n in cast("list[object]", result.get("notes") or []))
        return result

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Delete the objects, or undo what the stored record lists."""
        self._run(ctx, "remove", **({"record": self._stored_record(ctx)} if self.record else {}))
        return () if self.store_key is None else (self.store_key,)


@dataclass(frozen=True)
class KeycloakUser:
    """Test user ptest-bootstrap-<key> with a random password, and the wanted roles the realm has.

    Admin calls go through auth.keycloak_admin.for_environment.
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

    def is_present(self, ctx: Context, /) -> bool:
        """The user exists, and its password is in the credentials Secret."""
        return for_environment(ctx.env).user_id(self.username) is not None and self.store_key in ctx.store.read()

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Recreate the user with a new password and the wanted roles and groups that exist."""
        admin = for_environment(ctx.env)
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
        admin = for_environment(ctx.env)
        user = admin.user_id(self.username)
        if user:
            admin.delete_user(user)
        return (self.store_key,)


@dataclass(frozen=True)
class OpenKlantActor:
    """Open Klant medewerker actor for a Keycloak test user, matched by e-mail (TA seed-ita-medewerker-actor).

    ITA answers 409 ACTOR_RETRIEVAL_ERROR without it. Goes through the API with the suite's own token.
    """

    user: str
    requires: tuple[str, ...] = ("openklant",)
    wiring: bool = False

    @property
    def name(self) -> str:
        """Step name."""
        return f"openklant-actor-{self.user}"

    @property
    def email(self) -> str:
        """The test user's e-mail, which ITA and KISS match the actor on."""
        return user_email(f"{PREFIX}-{self.user}")

    def _api(self, ctx: Context) -> tuple[requests.Session, str, dict[str, str]]:
        url = ctx.env.profile.urls["openklant"] + "/klantinteracties/api/v1/actoren"
        return ctx.env.session(), url, {"Authorization": f"Token {ctx.store.read()[OPENKLANT_STORE_KEY]}"}

    def _uuids(self, ctx: Context) -> list[str]:
        http, url, headers = self._api(ctx)
        params = {"actoridentificatorObjectId": self.email}
        response = expect_status(http.get(url, params=params, headers=headers), HTTPStatus.OK)
        return [str(a["uuid"]) for a in entries(cast("dict[str, object]", response.json()).get("results"))]

    def is_present(self, ctx: Context, /) -> bool:
        """An actor with the user's e-mail exists."""
        return OPENKLANT_STORE_KEY in ctx.store.read() and bool(self._uuids(ctx))

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Recreate the actor."""
        self.remove(ctx)
        http, url, headers = self._api(ctx)
        body = {
            "naam": f"{PREFIX}-{self.user}",
            "soortActor": "medewerker",
            "indicatieActief": True,
            "actoridentificator": {
                "objectId": self.email,
                "codeObjecttype": "mdw",
                "codeRegister": "msei",
                "codeSoortObjectId": "email",
            },
        }
        expect_status(http.post(url, json=body, headers=headers), HTTPStatus.CREATED)
        return {}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Delete the user's actors."""
        if OPENKLANT_STORE_KEY not in ctx.store.read():
            return ()
        http, url, headers = self._api(ctx)
        for uuid in self._uuids(ctx):
            expect_status(http.delete(f"{url}/{uuid}", headers=headers), HTTPStatus.NO_CONTENT)
        return ()


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


def django_user_step(component: str, key: str, groups: tuple[str, ...]) -> SnippetStep:
    """A local Django user ptest-bootstrap-<key> in a component, with groups and a random password."""
    username = f"{PREFIX}-{key}"
    params: dict[str, object] = {"username": username, "email": user_email(username), "groups": list(groups)}
    return SnippetStep(
        f"{component}-user-{key}", (component,), "django_user", django_password_key(component, key), params
    )


def django_password_key(component: str, key: str) -> str:
    """Key of a Django test user's password in the credentials Secret."""
    return f"{PREFIX.replace('-', '_')}_{component}_{key}_password"


def notifications_params(ctx: Context) -> dict[str, object]:
    """The Open Notificaties client secret, and Open Notificaties' URL as other apps reach it in the cluster."""
    env = ctx.env
    default = f"http://{env.deployment_for('opennotificaties')}.{env.profile.kube.namespace}/api/v1/"
    return {
        "secret": ctx.store.read().get(NRC_STORE_KEY, ""),  # empty only before opennotificaties-client ran
        "notificaties_url": env.profile.settings.get("opennotificaties_internal_url", default),
    }


def openzaak_client_step(  # pylint: disable=too-many-arguments  # mirrors the snippet's parameters
    name: str,
    client_id: str,
    store_key: str,
    *,
    owns_catalogus: bool = False,
    max_va: str = "zeer_geheim",
    exclude: tuple[str, ...] = (),
    components: dict[str, tuple[str, ...]] | None = None,
    catalogi_scopes: tuple[str, ...] = CATALOGI_SCOPES,
) -> SnippetStep:
    """A ZGW client in Open Zaak with rights on the test catalogus only (PLAN.md §11a)."""
    params: dict[str, object] = {
        "client_id": client_id,
        "scopes": {"ztc": list(catalogi_scopes)},
        "catalogus": {
            "domein": TEST_CATALOGUS_DOMEIN,
            "rsin": TEST_CATALOGUS_RSIN,
            "owns": owns_catalogus,
            "max_va": max_va,
            "exclude": list(exclude),
            "components": {c: list(p) for c, p in (ZGW_COMPONENTS if components is None else components).items()},
        },
    }
    return SnippetStep(name, ("openzaak",), "zgw_client", store_key, params)


def token_step(component: str, module: str, store_key: str) -> SnippetStep:
    """A TokenAuth step; the token's identifier is its store key."""
    params: dict[str, object] = {"module": module, "identifier": store_key}
    return SnippetStep(f"{component}-token", (component,), "token_auth", store_key, params)


STEPS: tuple[Step, ...] = (
    # podiumd-tests' own infra (infra/), for the integration chains (PLAN.md §4 phase 4).
    WebhookReceiver(),
    openzaak_client_step("openzaak-client", ZGW_CLIENT_ID, ZGW_STORE_KEY, owns_catalogus=True),
    # TA's restricted Open Formulieren client: vertrouwelijkheid openbaar at most, no deletes.
    openzaak_client_step(
        "openzaak-client-openbaar",
        ZGW_OPENBAAR_CLIENT_ID,
        ZGW_OPENBAAR_STORE_KEY,
        max_va="openbaar",
        exclude=("verwijderen",),
    ),
    # A client without any autorisatie (TA reg-22d).
    openzaak_client_step(
        "openzaak-client-noauth", ZGW_NOAUTH_CLIENT_ID, ZGW_NOAUTH_STORE_KEY, components={}, catalogi_scopes=()
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
            "besluittype": TEST_BESLUITTYPE,
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
        "openklant-notificaties",
        ("openklant", "opennotificaties"),
        "notifications_config",
        "ptest_bootstrap_openklant_notificaties_record",
        {"prefix": PREFIX, "client_id": NRC_CLIENT_ID},
        record=True,
        wiring=True,
        context_params=notifications_params,
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
    # Open Archiefbeheer role users (TA seed-oab-users: recordmanager-test, reviewer-test, ...).
    django_user_step("openarchiefbeheer", "recordmanager", ("Record Manager",)),
    django_user_step("openarchiefbeheer", "reviewer", ("Reviewer",)),
    django_user_step("openarchiefbeheer", "coreviewer", ("Co-reviewer",)),
    django_user_step("openarchiefbeheer", "archivist", ("Archivist",)),
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
    OpenKlantActor("kcc"),
    KeycloakUser("inwoner", attributes={"bsn": ["999990019"]}),
    KeycloakUser("inwoner2", attributes={"bsn": ["999990038"]}),
    KeycloakUser("bedrijf", attributes={"kvk": ["68750110"], "vestigingsnummer": ["000038509564"]}),
)
