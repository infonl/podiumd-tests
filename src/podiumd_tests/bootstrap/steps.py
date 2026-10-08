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
from podiumd_tests.bootstrap.names import CATALOGI_SCOPES
from podiumd_tests.bootstrap.names import ITA_OBJECTTYPES
from podiumd_tests.bootstrap.names import KANALEN
from podiumd_tests.bootstrap.names import NRC_CLIENT_ID
from podiumd_tests.bootstrap.names import NRC_STORE_KEY
from podiumd_tests.bootstrap.names import OBJECTEN_STORE_KEY
from podiumd_tests.bootstrap.names import OPENKLANT_OPENINWONER_STORE_KEY
from podiumd_tests.bootstrap.names import OPENKLANT_STORE_KEY
from podiumd_tests.bootstrap.names import PREFIX
from podiumd_tests.bootstrap.names import PRODUCTAANVRAAG_OBJECTTYPE
from podiumd_tests.bootstrap.names import TEST_BESLUITTYPE
from podiumd_tests.bootstrap.names import TEST_CATALOGUS_DOMEIN
from podiumd_tests.bootstrap.names import TEST_CATALOGUS_RSIN
from podiumd_tests.bootstrap.names import TEST_FORM
from podiumd_tests.bootstrap.names import TEST_IOT
from podiumd_tests.bootstrap.names import TEST_ZAAKTYPE
from podiumd_tests.bootstrap.names import ZGW_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_COMPONENTS
from podiumd_tests.bootstrap.names import ZGW_NOAUTH_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_NOAUTH_STORE_KEY
from podiumd_tests.bootstrap.names import ZGW_OPENBAAR_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_OPENBAAR_STORE_KEY
from podiumd_tests.bootstrap.names import ZGW_PRODUCTAANVRAAG_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_PRODUCTAANVRAAG_STORE_KEY
from podiumd_tests.bootstrap.names import ZGW_STORE_KEY
from podiumd_tests.bootstrap.oidc_mock import KeycloakOidcMock
from podiumd_tests.bootstrap.oidc_mock import oidc_params
from podiumd_tests.bootstrap.omc import OmcAbonnement
from podiumd_tests.clients.platform import openklant_client
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openklant import delete_partij
from podiumd_tests.seed.openklant import partijen_of
from podiumd_tests.webhook import WebhookReceiver

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.bootstrap import Context
    from podiumd_tests.bootstrap import Step


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
        """The user exists with the wanted attributes, and its password is in the credentials Secret."""
        user = for_environment(ctx.env).user(self.username)
        if user is None or self.store_key not in ctx.store.read():
            return False
        attributes = section(user, "attributes")
        return all(attributes.get(name) == values for name, values in self.attributes.items())

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
    """The ZGW client secret, and Open Zaak's URL as Open Formulieren calls it.

    Default: the profile URL, which is also the URL Open Zaak puts in its own resources; a
    different api_root would not match the zaaktype URLs Open Zaak returns.
    """
    env = ctx.env
    return {
        "secret": ctx.store.read().get(ZGW_STORE_KEY, ""),  # empty only before openzaak-client ran
        "openzaak_url": env.profile.settings.get("openzaak_internal_url", env.profile.urls["openzaak"]),
    }


def openinwoner_openklant_params(ctx: Context) -> dict[str, object]:
    """Open Klant's API as Open Inwoner calls it, its token, and the contact flow's settings.

    Questions go to the KCC test user's medewerker actor (bootstrap step openklant-actor-kcc).
    """
    openklant = openklant_client(ctx.env)
    actor = openklant.list("actoren", {"actoridentificatorObjectId": user_email(KCC.username)})
    if not actor:
        msg = "no Open Klant actor for the KCC test user: run bootstrap step openklant-actor-kcc first"
        raise LookupError(msg)
    return {
        "api_root": ctx.env.profile.urls["openklant"] + "/klantinteracties/api/v1/",
        "token": ctx.store.read().get(OPENKLANT_OPENINWONER_STORE_KEY, ""),
        "config": {
            "mijn_vragen_kanaal": "contactformulier",
            "mijn_vragen_actor": str(actor[0]["uuid"]),
            "mijn_vragen_organisatie_naam": "podiumd-tests",
            "interne_taak_gevraagde_handeling": "Vraag beantwoorden",
            "interne_taak_toelichting": "Beantwoorden vraag inwoner",
            # No cached partij: a test removes the partij Open Inwoner made for it.
            "partij_cache_timeout": 0,
        },
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


def token_step(component: str, module: str, store_key: str, **extra: object) -> SnippetStep:
    """A TokenAuth step; the token's identifier is its store key."""
    params: dict[str, object] = {"module": module, "identifier": store_key, **extra}
    return SnippetStep(f"{component}-token", (component,), "token_auth", store_key, params)


def productaanvraag_zaaktypen(ctx: Context) -> dict[str, object]:
    """Read and delete rights on the zaaktype ZAC starts for a productaanvraag; none without the setting."""
    zaaktype = ctx.env.profile.settings.get("productaanvraag_zaaktype")
    if not zaaktype:
        return {}
    return {
        "zaaktypen": {
            "identificaties": [zaaktype],
            "scopes": ["zaken.lezen", "zaken.verwijderen"],
            "max_va": "zeer_geheim",
            "base_url": ctx.env.profile.urls["openzaak"],
        }
    }


# Open Archiefbeheer test users per role (key -> OAB group).
OAB_ROLES = {
    "recordmanager": "Record Manager",
    "reviewer": "Reviewer",
    "coreviewer": "Co-reviewer",
    "archivist": "Archivist",
}
# The klantcontactmedewerker of KISS and ITA (TA kcc-medewerker).
KCC = KeycloakUser(
    "kcc",
    realm_roles=("Klantcontactmedewerker",),
    client_roles=(("kiss", "Klantcontactmedewerker"), ("ita", "ITA_Gebruiker")),
    # ITA refuses a login without it ("Verwachtewaarde voor de samaccountname ontbreekt").
    attributes={"samaccountname": [f"{PREFIX}-kcc"]},
)
# Test identities for DigiD and eHerkenning logins (TA testinwoner, testinwoner2, testbedrijf):
# the Keycloak attributes become the bsn and eHerkenning claims of the mock.
IDENTITIES = (
    KeycloakUser("inwoner", attributes={"bsn": ["999990019"]}),
    # Not TA's 999990038: it fails the eleven-test, and Open Klant refuses it.
    KeycloakUser("inwoner2", attributes={"bsn": ["999993653"]}),
    KeycloakUser("bedrijf", attributes={"kvk": ["68750110"], "vestigingsnummer": ["000037178601"]}),
)
# Open Inwoner's portal pages; the contact form is a plugin on a page with its template.
OI_PAGES = [
    {"slug": "welkom", "title": "Welkom bij PodiumD", "template": "cms/fullwidth.html", "home": True},
    {
        "slug": "mijn-zaken",
        "title": "Mijn zaken",
        "template": "cms/fullwidth.html",
        "apphook": "CasesApphook",
        "namespace": "cases",
    },
    {
        "slug": "mijn-profiel",
        "title": "Mijn profiel",
        "template": "cms/fullwidth.html",
        "apphook": "ProfileApphook",
        "namespace": "profile",
    },
    {
        "slug": "berichten",
        "title": "Berichten",
        "template": "cms/fullwidth.html",
        "apphook": "InboxApphook",
        "namespace": "inbox",
    },
    {
        "slug": "contactformulier",
        "title": "Contactformulier",
        "template": "cms/contactform/form_outer.html",
        "plugin": {"slot": "contact_form", "type": "ContactFormPlugin"},
    },
]
# Open Formulieren's DigiD level of assurance when the mock sends none.
LOA_DEFAULT = "urn:oasis:names:tc:SAML:2.0:ac:classes:MobileTwoFactorContract"
# Where Open Inwoner finds the eHerkenning claims (mappers in oidc_mock.SCOPES).
EHERKENNING_CLAIMS = {
    "legal_subject_claim_path": ["urn:etoegang:core:LegalSubjectID"],
    "branch_number_claim_path": ["urn:etoegang:1.9:ServiceRestriction:Vestigingsnr"],
    "identifier_type_claim_path": ["namequalifier"],
}


# Open Formulieren's level of assurance: the mock sends none, so every login gets the default.
OF_LOA = {"claim_path": ["authsp_level"], "default": LOA_DEFAULT, "value_mapping": []}


def openinwoner_number(user: KeycloakUser) -> dict[str, str]:
    """The bsn or kvk an Open Inwoner account of a test identity is found by."""
    key = "bsn" if "bsn" in user.attributes else "kvk"
    return {key: user.attributes[key][0]}


@dataclass(frozen=True)
class OpenInwonerPartijen:
    """Open Klant partijen of the test identities, which Open Inwoner creates at their first login.

    Nothing to create: unbootstrap deletes them, so no test identity outlives the bootstrap.
    """

    name: str = "openinwoner-partijen"
    requires: tuple[str, ...] = ("openinwoner", "openklant")
    wiring: bool = True

    def is_present(self, _ctx: Context, /) -> bool:
        """Always: Open Inwoner creates the partijen."""
        return True

    def apply(self, _ctx: Context, /) -> dict[str, str]:
        """Nothing."""
        return {}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Delete the partijen identified by a test identity's vestigingsnummer, bsn or kvk."""
        if OPENKLANT_STORE_KEY not in ctx.store.read():
            return ()
        openklant = openklant_client(ctx.env)
        # A vestiging's partij goes first: its identificator protects the kvk_nummer's.
        for key in ("vestigingsnummer", "bsn", "kvk"):
            for user in IDENTITIES:
                for number in user.attributes.get(key, []):
                    for partij in partijen_of(openklant, number):
                        delete_partij(openklant, partij)
        return ()


def openinwoner_account(user: KeycloakUser) -> dict[str, str]:
    """The Open Inwoner account prepared for a DigiD test identity: its bsn, e-mail and name.

    The DigiD login uses it as a complete profile; for eHerkenning Open Inwoner always
    creates its own account, so none is prepared.
    """
    return {**openinwoner_number(user), "email": user_email(user.username), "first": "PodiumD", "last": user.username}


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
    token_step(
        "objecten",
        "objects.token.models",
        OBJECTEN_STORE_KEY,
        object_types=[PRODUCTAANVRAAG_OBJECTTYPE, *ITA_OBJECTTYPES],
    ),
    # Only reads and deletes the zaken ZAC creates for the test's productaanvragen.
    SnippetStep(
        "openzaak-client-productaanvraag",
        ("openzaak", "zac"),
        "zgw_client",
        ZGW_PRODUCTAANVRAAG_STORE_KEY,
        {"client_id": ZGW_PRODUCTAANVRAAG_CLIENT_ID, "scopes": {}},
        context_params=productaanvraag_zaaktypen,
    ),
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
    OmcAbonnement(),
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
    # Open Archiefbeheer role users (TA seed-oab-users: recordmanager-test, reviewer-test, ...);
    # OAB logs them in locally, as in podiumd-minikube.
    *(django_user_step("openarchiefbeheer", key, (group,)) for key, group in OAB_ROLES.items()),
    KCC,
    KeycloakUser(
        "admin",
        realm_roles=("Registreerders", "Behandelaar", "Coordinator", "Functioneel-beheerder", "beheerder_elk_domein"),
        client_roles=(("pabc", "administrator"),),
        groups=("beheerders-elk-domein",),
    ),
    OpenKlantActor("kcc"),
    *IDENTITIES,
    # Wiring W1: DigiD and eHerkenning through Keycloak's mock (TA seed-*-oidc-mock.sh, seed-of-digid-oidc.sh).
    KeycloakOidcMock(),
    SnippetStep(
        "openinwoner-oidc-mock",
        ("openinwoner", "keycloak"),
        "oidc_mock",
        "ptest_bootstrap_openinwoner_oidc_mock_record",
        {
            "clients": {
                "oidc-digid": {
                    "provider": f"{PREFIX}-digid",
                    "scopes": ["openid", "bsn"],
                    "options": {"identity_settings": {"bsn_claim_path": ["bsn"]}},
                },
                "oidc-eherkenning": {
                    "provider": f"{PREFIX}-eherkenning",
                    "scopes": ["openid", "eherkenning"],
                    "options": {"identity_settings": EHERKENNING_CLAIMS},
                },
            },
            "eherkenning_site": True,
            "accounts": [openinwoner_account(u) for u in IDENTITIES if "bsn" in u.attributes],
            "identities": [openinwoner_number(u) for u in IDENTITIES],
        },
        record=True,
        wiring=True,
        context_params=oidc_params("openinwoner"),
    ),
    # Open Formulieren registers a zaak with a valid initiator only for a DigiD login (TA spec 183).
    SnippetStep(
        "openformulieren-oidc-mock",
        ("openformulieren", "keycloak"),
        "oidc_mock",
        "ptest_bootstrap_openformulieren_oidc_mock_record",
        {
            "clients": {
                "oidc-digid": {
                    "provider": f"{PREFIX}-digid",
                    "scopes": ["openid", "bsn"],
                    "options": {"identity_settings": {"bsn_claim_path": ["bsn"]}, "loa_settings": OF_LOA},
                },
                "oidc-eherkenning": {
                    "provider": f"{PREFIX}-eherkenning",
                    "scopes": ["openid", "eherkenning"],
                    # The mock sends no acting subject; Open Formulieren needs it only in strict mode.
                    "options": {
                        "identity_settings": {**EHERKENNING_CLAIMS, "acting_subject_claim_path": ["acting_subject"]},
                        "loa_settings": OF_LOA,
                    },
                },
            },
            "form": TEST_FORM,
            "form_backends": ["digid_oidc", "eherkenning_oidc"],
        },
        record=True,
        wiring=True,
        context_params=oidc_params("openformulieren"),
    ),
    # Wiring W5: Open Inwoner's portal pages (TA seed-oi-cms-pages.sh).
    SnippetStep(
        "openinwoner-cms-pages",
        ("openinwoner",),
        "oi_cms_pages",
        "ptest_bootstrap_openinwoner_cms_pages_record",
        {"pages": OI_PAGES, "contact_email": "noreply@example.invalid"},
        record=True,
        wiring=True,
    ),
    # Wiring W4: Open Inwoner shows zaken through an API group (TA seed-oi-bedrading.sh).
    SnippetStep(
        "openinwoner-zgw-group",
        ("openinwoner", "openzaak"),
        "oi_zgw_group",
        "ptest_bootstrap_openinwoner_zgw_group_record",
        {"name": f"{PREFIX}-openzaak"},
        record=True,
        wiring=True,
        context_params=lambda ctx: {"zaken_url": ctx.env.profile.urls["openzaak"] + "/zaken/api/v1/"},
    ),
    # Open Inwoner scans uploads with the environment's ClamAV (profile setting clamav), for TA 123.
    SnippetStep(
        "openinwoner-virus-scan",
        ("openinwoner",),
        "oi_virus_scan",
        "ptest_bootstrap_openinwoner_virus_scan_record",
        {},
        record=True,
        wiring=True,
        context_params=lambda ctx: {"clamav": ctx.env.profile.settings.get("clamav", "")},
    ),
    # The test zaaktype in Open Inwoner, with contact form and document upload (TA zgw_import_data).
    SnippetStep(
        "openinwoner-zaaktype-config",
        ("openinwoner", "openzaak"),
        "oi_zaaktype_config",
        "ptest_bootstrap_openinwoner_zaaktype_config_record",
        {
            "group": f"{PREFIX}-openzaak",
            "domein": TEST_CATALOGUS_DOMEIN,
            "rsin": TEST_CATALOGUS_RSIN,
            "identificatie": TEST_ZAAKTYPE,
            "iot_omschrijving": TEST_IOT,
        },
        record=True,
        wiring=True,
    ),
    # Wiring W6 and W8: Open Inwoner's klantensysteem is Open Klant 2, with the contact flow
    # (TA seed-oi-openklant2.sh, seed-oi-contactflow.sh).
    SnippetStep(
        "openklant-token-openinwoner",
        ("openklant",),
        "token_auth",
        OPENKLANT_OPENINWONER_STORE_KEY,
        {"module": "openklant.components.token.models", "identifier": OPENKLANT_OPENINWONER_STORE_KEY},
        wiring=True,
    ),
    SnippetStep(
        "openinwoner-openklant",
        ("openinwoner", "openklant"),
        "oi_openklant",
        "ptest_bootstrap_openinwoner_openklant_record",
        {"subjects": ["Algemene vraag", "Vraag over zaak"], "group": f"{PREFIX}-openzaak"},
        record=True,
        wiring=True,
        context_params=openinwoner_openklant_params,
    ),
    OpenInwonerPartijen(),
)
