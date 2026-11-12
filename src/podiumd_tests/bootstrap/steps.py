"""The bootstrap steps, in the order they are applied (unbootstrap goes in reverse)."""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.auth.keycloak_admin import user_email
from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.basisregistraties import KVK_TEST_NUMMER
from podiumd_tests.basisregistraties import KVK_TEST_VESTIGING
from podiumd_tests.bootstrap import names
from podiumd_tests.bootstrap.bpmn import ZacBpmnProcess
from podiumd_tests.bootstrap.bpmn import ZacBpmnProductaanvraag
from podiumd_tests.bootstrap.inway import InwayConsumers
from podiumd_tests.bootstrap.keycloak import KeycloakRoles
from podiumd_tests.bootstrap.keycloak import KeycloakUser
from podiumd_tests.bootstrap.kiss import KissKanalen
from podiumd_tests.bootstrap.oidc_mock import KeycloakOidcMock
from podiumd_tests.bootstrap.oidc_mock import oidc_params
from podiumd_tests.bootstrap.omc import OmcAbonnement
from podiumd_tests.bootstrap.snippet_step import SnippetStep
from podiumd_tests.bootstrap.zac import AANVULLENDE_INFORMATIE
from podiumd_tests.bootstrap.zac import EMAIL_CONFIRMATION
from podiumd_tests.bootstrap.zac import ZacCatalogusStep
from podiumd_tests.bootstrap.zac import ZacParameters
from podiumd_tests.clients.platform import objecten_client
from podiumd_tests.clients.platform import openklant_client
from podiumd_tests.json_data import entries
from podiumd_tests.mock_server import MockServer
from podiumd_tests.mock_server import mock_server_root
from podiumd_tests.payments import OGONE_ENDPOINT
from podiumd_tests.payments import OGONE_HASH
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openklant import delete_partij
from podiumd_tests.seed.openklant import partijen_of
from podiumd_tests.seed.openzaak import today
from podiumd_tests.zac import HEROPEND

if TYPE_CHECKING:
    import requests

    from podiumd_tests.bootstrap.runner import Context
    from podiumd_tests.bootstrap.runner import Step
    from podiumd_tests.json_data import JsonObject


# The groep of the KCC test user in ITA: ITA shows a contactverzoek only to members of the
# afdeling or groep it is assigned to (or to a functioneel beheerder).
ITA_GROEP = f"{names.PREFIX}-groep"


@dataclass(frozen=True)
class ItaMedewerker:
    """The Medewerker object in Objecten of a Keycloak test user, in groep ITA_GROEP.

    ITA finds it by the identificatie the user's samaccountname claim carries.
    """

    user: KeycloakUser
    requires: tuple[str, ...] = ("objecten", "ita")
    wiring: bool = False

    @property
    def name(self) -> str:
        """Step name."""
        return f"objecten-medewerker-{self.user.key}"

    @property
    def identificatie(self) -> str:
        """The user's samaccountname."""
        return self.user.attributes["samaccountname"][0]

    def is_present(self, ctx: Context, /) -> bool:
        """Return whether a Medewerker object with the user's identificatie exists."""
        return names.OBJECTEN_STORE_KEY in ctx.store.read() and bool(self._found(ctx))

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Recreate the Medewerker object."""
        self.remove(ctx)
        data = {
            "identificatie": self.identificatie,
            "email": user_email(self.user.username),
            "groepen": [{"groepsnaam": ITA_GROEP}],
            "afdelingen": [],
        }
        body = {
            "type": objecttype_url(ctx.env, "Medewerker"),
            "record": {"typeVersion": 1, "data": data, "startAt": today()},
        }
        objecten_client(ctx.env).post("objects", body)
        return {}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Delete the user's Medewerker objects."""
        if names.OBJECTEN_STORE_KEY not in ctx.store.read():
            return ()
        for found in self._found(ctx):
            objecten_client(ctx.env).delete(str(found["url"]))
        return ()

    def _found(self, ctx: Context) -> list[JsonObject]:
        query = {"data_attr": f"identificatie__exact__{self.identificatie}"}
        return objecten_client(ctx.env).list("objects", query)


def _actoren_api(ctx: Context) -> tuple[requests.Session, str, dict[str, str]]:
    url = f"{ctx.env.profile.urls['openklant']}/klantinteracties/api/v1/actoren"
    return ctx.env.session(), url, {"Authorization": f"Token {ctx.store.read()[names.OPENKLANT_STORE_KEY]}"}


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
        return user_email(f"{names.PREFIX}-{self.user}")

    def is_present(self, ctx: Context, /) -> bool:
        """Return whether an actor with the user's e-mail exists."""
        return names.OPENKLANT_STORE_KEY in ctx.store.read() and bool(self._uuids(ctx))

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Recreate the actor."""
        self.remove(ctx)
        http, url, headers = _actoren_api(ctx)
        body = {
            "naam": f"{names.PREFIX}-{self.user}",
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
        if names.OPENKLANT_STORE_KEY not in ctx.store.read():
            return ()
        http, url, headers = _actoren_api(ctx)
        for uuid in self._uuids(ctx):
            expect_status(http.delete(f"{url}/{uuid}", headers=headers), HTTPStatus.NO_CONTENT)
        return ()

    def _uuids(self, ctx: Context) -> list[str]:
        http, url, headers = _actoren_api(ctx)
        params = {"actoridentificatorObjectId": self.email}
        response = expect_status(http.get(url, params=params, headers=headers), HTTPStatus.OK)
        actors = entries(cast("dict[str, object]", response.json()).get("results"))
        return [str(actor["uuid"]) for actor in actors]


def openformulieren_params(ctx: Context) -> dict[str, object]:
    """Return the ZGW client secret, and Open Zaak's URL as Open Formulieren calls it.

    Default: the profile URL, which is also the URL Open Zaak puts in its own resources; a
    different api_root would not match the zaaktype URLs Open Zaak returns.
    """
    env = ctx.env
    return {
        "secret": ctx.store.read().get(names.ZGW_STORE_KEY, ""),  # empty only before openzaak-client ran
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
        "api_root": f"{ctx.env.profile.urls['openklant']}/klantinteracties/api/v1/",
        "token": ctx.store.read().get(names.OPENKLANT_OI_STORE_KEY, ""),
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


def django_user_step(  # noqa: PLR0913  # mirrors the snippet's parameters
    component: str,
    key: str,
    groups: tuple[str, ...] = (),
    *,
    staff: bool = True,
    fields: dict[str, str] | None = None,
    api_token: bool = False,
) -> SnippetStep:
    """Return a component's local Django user ptest-bootstrap-<key>, with groups and a random password or API token."""
    username = f"{names.PREFIX}-{key}"
    params: dict[str, object] = {
        "username": username,
        "email": user_email(username),
        "groups": list(groups),
        "staff": staff,
        "fields": fields or {},
        "api_token": api_token,
    }
    return SnippetStep(
        f"{component}-user-{key}",
        (component,),
        "django_user",
        django_secret_key(component, key, "token" if api_token else "password"),
        params,
    )


def django_secret_key(component: str, key: str, kind: str = "password") -> str:
    """Key of a Django test user's password or API token in the credentials Secret."""
    return f"{names.PREFIX.replace('-', '_')}_{component}_{key}_{kind}"


def openzaak_client_step(  # noqa: PLR0913  # mirrors the snippet's parameters
    name: str,
    client_id: str,
    store_key: str,
    *,
    owns_catalogus: bool = False,
    max_va: str = "zeer_geheim",
    exclude: tuple[str, ...] = (),
    components: dict[str, tuple[str, ...]] | None = None,
    catalogi_scopes: tuple[str, ...] = names.CATALOGI_SCOPES,
) -> SnippetStep:
    """Return a ZGW client in Open Zaak with rights on the test catalogus only."""
    granted = names.ZGW_COMPONENTS if components is None else components
    params: dict[str, object] = {
        "client_id": client_id,
        "scopes": {"ztc": list(catalogi_scopes)},
        "catalogus": {
            "domein": names.TEST_CATALOGUS_DOMEIN,
            "rsin": names.TEST_CATALOGUS_RSIN,
            "owns": owns_catalogus,
            "max_va": max_va,
            "exclude": list(exclude),
            "components": {component: list(prefixes) for component, prefixes in granted.items()},
        },
    }
    return SnippetStep(name, ("openzaak",), "zgw_client", store_key, params)


def token_step(component: str, modules: tuple[str, ...], store_key: str, **extra: object) -> SnippetStep:
    """Return a TokenAuth step in the first of the token models modules the app has; the identifier is its store key."""
    params: dict[str, object] = {"modules": modules, "identifier": store_key, **extra}
    return SnippetStep(f"{component}-token", (component,), "token_auth", store_key, params)


def productaanvraag_zaaktypen(ctx: Context) -> dict[str, object]:
    """Read and delete rights on the zaaktype ZAC starts zaken of, and on their documents; none without the setting."""
    zaaktype = ctx.env.profile.settings.get("productaanvraag_zaaktype")
    if not zaaktype:
        return {}
    return {
        "zaaktypen": {
            "identificaties": [zaaktype],
            # geforceerd-bijwerken: Open Zaak refuses to delete a besluit of a closed zaak without it.
            "scopes": ["zaken.lezen", "zaken.verwijderen", "zaken.geforceerd-bijwerken"],
            # ZAC adds documents, e.g. the ontvangstbevestiging it sent; Open Zaak keeps them when the zaak goes.
            "document_scopes": ["documenten.lezen", "documenten.verwijderen"],
            # A zaak with a besluit cannot be deleted before the besluit.
            "besluit_scopes": ["besluiten.lezen", "besluiten.verwijderen"],
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
    # The functioneel beheerder: the only role that may change OAB's archive configuration.
    "beheerder": "Administrator",
}
# The test admin: ZAC beheerder, PABC administrator, KISS beheerder and redacteur, ZaakBrug console tester, admin of
# the Django apps' SSO.
ADMIN = KeycloakUser(
    "admin",
    # beheerders: podiumd's pabc-dataset.json maps it to every ZAC role in all domains (ExternalsPodiumD).
    realm_roles=(
        "Registreerders",
        "Behandelaar",
        "Coordinator",
        "Functioneel-beheerder",
        "beheerders",
        names.ZAC_FUNCTIONAL_ROLE,
    ),
    # zaakbrug_admin: Frank!Framework's IbisTester on ZaakBrug's console (oauthRoleMapping).
    client_roles=(
        ("pabc", "administrator"),
        ("kiss", "Beheerder"),
        ("kiss", "Redacteur"),
        ("zaakbrug", "zaakbrug_admin"),
    ),
    groups=("beheerders",),
)
# The klantcontactmedewerker of KISS and ITA (TA kcc-medewerker).
KCC = KeycloakUser(
    "kcc",
    realm_roles=("Klantcontactmedewerker",),
    client_roles=(("kiss", "Klantcontactmedewerker"), ("ita", "ITA_Gebruiker")),
    # ITA refuses a login without it ("Verwachtewaarde voor de samaccountname ontbreekt").
    attributes={"samaccountname": [f"{names.PREFIX}-kcc"]},
)
# One user per ZAC application role of step zac-bpmn-process, with only that realm role; keycloak-roles creates
# the realm roles, so the users need wiring.
ZAC_ROLE_USERS = {
    roles[0]: KeycloakUser(name.removeprefix(f"{names.PREFIX}-"), realm_roles=(name,), wiring=True)
    for name, roles in names.ZAC_FUNCTIONAL_ROLES.items()
    if name != names.ZAC_FUNCTIONAL_ROLE
}
# ITA's functioneel beheerder: Alle contactverzoeken, reopening a closed contactverzoek.
ITA_BEHEERDER = KeycloakUser(
    "ita-beheerder",
    client_roles=(("ita", "ITA_Gebruiker"), ("ita", "ITA_Functioneel_Beheerder")),
    attributes={"samaccountname": [f"{names.PREFIX}-ita-beheerder"]},
)
# Test identities for DigiD and eHerkenning logins (TA testinwoner, testinwoner2, testbedrijf):
# the Keycloak attributes become the bsn and eHerkenning claims of the mock.
IDENTITIES = (
    KeycloakUser("inwoner", attributes={"bsn": [EREBOS]}),
    # Not TA's 999990038: it fails the eleven-test, and Open Klant refuses it.
    KeycloakUser("inwoner2", attributes={"bsn": ["999993653"]}),
    KeycloakUser("bedrijf", attributes={"kvk": [KVK_TEST_NUMMER], "vestigingsnummer": [KVK_TEST_VESTIGING]}),
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
        "slug": "onderwerpen",
        "title": "Onderwerpen",
        "template": "cms/fullwidth.html",
        # Search results link to product pages through this namespace; without it every search with hits fails.
        "apphook": "ProductsApphook",
        "namespace": "products",
    },
    {
        "slug": "samenwerken",
        "title": "Samenwerken",
        "template": "cms/fullwidth.html",
        "apphook": "CollaborateApphook",
        "namespace": "collaborate",
    },
    {
        "slug": "contactformulier",
        "title": "Contactformulier",
        "template": "cms/contactform/form_outer.html",
        # The apphook's view puts the form in the context; without it the plugin renders empty fields.
        "apphook": "OpenklantApphook",
        "namespace": "openklant",
        "plugin": {"slot": "contact_form", "type": "ContactFormPlugin"},
    },
]
# A gemeente employee in Open Inwoner who starts a samenwerking (plan) with an inwoner or company.
OI_BEGELEIDER = django_user_step(
    "openinwoner",
    "begeleider",
    staff=False,
    fields={"contact_type": "begeleider", "first_name": "PodiumD", "last_name": "Begeleider"},
)
# An Open Formulieren form editor (its own group Redacteurs) that changes test forms through the API.
OF_REDACTEUR = django_user_step("openformulieren", "redacteur", ("Redacteurs",), api_token=True)
# The test form's fields. The name makes the initiator of an anonymous submission: without it
# Open Formulieren sends Open Zaak an initiator rol without betrokkeneIdentificatie, which it refuses.
NAW = [
    {
        "type": "textfield",
        "key": "achternaam",
        "label": "Achternaam",
        "validate": {"required": True},
        "registration": {"attribute": "initiator_geslachtsnaam"},
    },
    {
        "type": "textfield",
        "key": "voornamen",
        "label": "Voornamen",
        "registration": {"attribute": "initiator_voornamen"},
    },
]
TEST_FORM_COMPONENTS = [
    {"type": "textfield", "key": "klacht_omschrijving", "label": "Omschrijving", "validate": {"required": True}},
    *NAW,
]
# The NAW values the tests fill in.
NAW_DATA = {"achternaam": "Testpersoon", "voornamen": "PodiumD"}
# Open Formulieren's registration of a test form as a zaak of the test zaaktype (step openformulieren-zgw-group).
ZGW_REGISTRATION = {
    "backend": "zgw-create-zaak",
    "api_group": names.PREFIX,
    "options": {
        "catalogue": {"domain": names.TEST_CATALOGUS_DOMEIN, "rsin": names.TEST_CATALOGUS_RSIN},
        "case_type_identification": names.TEST_ZAAKTYPE,
        "document_type_description": names.TEST_IOT,
        "organisatie_rsin": names.TEST_CATALOGUS_RSIN,
        "zaak_vertrouwelijkheidaanduiding": "openbaar",
    },
}
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
    """Return the bsn or kvk an Open Inwoner account of a test identity is found by."""
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

    def is_present(self, _ctx: Context, /) -> bool:  # noqa: PLR6301  # a Step method
        """Return True: Open Inwoner creates the partijen."""
        return True

    def apply(self, _ctx: Context, /) -> dict[str, str]:  # noqa: PLR6301  # a Step method
        """Nothing."""
        return {}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:  # noqa: PLR6301  # a Step method
        """Delete the partijen identified by a test identity's vestigingsnummer, bsn or kvk."""
        if names.OPENKLANT_STORE_KEY not in ctx.store.read():
            return ()
        openklant = openklant_client(ctx.env)
        # A vestiging's partij goes first: its identificator protects the kvk_nummer's.
        for key in ("vestigingsnummer", "bsn", "kvk"):
            numbers = [number for user in IDENTITIES for number in user.attributes.get(key, [])]
            for number in numbers:
                for partij in partijen_of(openklant, number):
                    delete_partij(openklant, partij)
        return ()


def openinwoner_account(user: KeycloakUser) -> dict[str, str]:
    """Return the Open Inwoner account prepared for a DigiD test identity: its bsn, e-mail and name.

    The DigiD login uses it as a complete profile; for eHerkenning Open Inwoner always
    creates its own account, so none is prepared.
    """
    return {**openinwoner_number(user), "email": user_email(user.username), "first": "PodiumD", "last": user.username}


STEPS: tuple[Step, ...] = (
    # podiumd-tests' own infra (infra/), for the integration chains.
    MockServer(),
    InwayConsumers(),
    openzaak_client_step("openzaak-client", names.ZGW_CLIENT_ID, names.ZGW_STORE_KEY, owns_catalogus=True),
    # TA's restricted Open Formulieren client: vertrouwelijkheid openbaar at most, no deletes.
    openzaak_client_step(
        "openzaak-client-openbaar",
        names.ZGW_OPENBAAR_CLIENT_ID,
        names.ZGW_OPENBAAR_STORE_KEY,
        max_va="openbaar",
        exclude=("verwijderen",),
    ),
    # A client without any autorisatie (TA reg-22d).
    openzaak_client_step(
        "openzaak-client-noauth",
        names.ZGW_NOAUTH_CLIENT_ID,
        names.ZGW_NOAUTH_STORE_KEY,
        components={},
        catalogi_scopes=(),
    ),
    # A client that cannot change a closed zaak, reopen it or force a document unlock (ZGW rules zrc-007, zrc-008).
    openzaak_client_step(
        "openzaak-client-gesloten",
        names.ZGW_GESLOTEN_CLIENT_ID,
        names.ZGW_GESLOTEN_STORE_KEY,
        exclude=("geforceerd", "heropenen"),
    ),
    SnippetStep(
        "opennotificaties-client",
        ("opennotificaties",),
        "zgw_client",
        names.NRC_STORE_KEY,
        {"client_id": names.NRC_CLIENT_ID, "scopes": {"nrc": ["notificaties.consumeren", "notificaties.publiceren"]}},
    ),
    token_step("openklant", ("openklant.components.token.models",), names.OPENKLANT_STORE_KEY),
    SnippetStep(
        "openvtb-token", ("openvtb",), "openvtb_token", names.OPENVTB_STORE_KEY, {"username": f"{names.PREFIX}-openvtb"}
    ),
    token_step(
        "objecttypen",
        # Open Object (podiumd 4.10) serves the Objecttypen API with Objecten's tokens.
        ("objecttypes.token.models", "objects.token.models"),
        names.OBJECTTYPEN_STORE_KEY,
        objecttypen_api=True,
    ),
    token_step(
        "objecten",
        ("objects.token.models",),
        names.OBJECTEN_STORE_KEY,
        object_types=[names.PRODUCTAANVRAAG_OBJECTTYPE, *names.ITA_OBJECTTYPES, *names.KISS_OBJECTTYPES],
    ),
    # A besluittype for the zaaktype ZAC handles, where the profile allows it: ZAC's inrichtingscheck needs one.
    # Before openzaak-client-productaanvraag, which gets rights on it.
    ZacCatalogusStep(
        "openzaak-zac-besluittype",
        ("openzaak", "zac", "keycloak"),
        "openzaak_besluittype",
        None,
        {"omschrijving": f"{names.PREFIX}-zac-besluit"},
        wiring=True,
        admin=ADMIN,
        context_params=lambda ctx: {
            "zaaktype": ctx.env.profile.settings.get("productaanvraag_zaaktype", "")
            if ctx.env.profile.is_allowed("zac_besluittype")
            else ""
        },
    ),
    # Only reads and deletes the zaken ZAC creates for the test's productaanvragen.
    SnippetStep(
        "openzaak-client-productaanvraag",
        ("openzaak", "zac"),
        "zgw_client",
        names.ZGW_PRODUCTAANVRAAG_STORE_KEY,
        {"client_id": names.ZGW_PRODUCTAANVRAAG_CLIENT_ID, "scopes": {}},
        context_params=productaanvraag_zaaktypen,
    ),
    SnippetStep(
        "openzaak-zaaktype",
        ("openzaak",),
        "openzaak_zaaktype",
        None,
        {
            "domein": names.TEST_CATALOGUS_DOMEIN,
            "rsin": names.TEST_CATALOGUS_RSIN,
            "identificatie": names.TEST_ZAAKTYPE,
            "iot_omschrijving": names.TEST_IOT,
            "besluittype": names.TEST_BESLUITTYPE,
        },
    ),
    SnippetStep(
        "openzaak-besluittype-bijlage",
        ("openzaak",),
        "openzaak_besluittype_iot",
        None,
        {
            "domein": names.TEST_CATALOGUS_DOMEIN,
            "rsin": names.TEST_CATALOGUS_RSIN,
            "besluittype": names.TEST_BESLUITTYPE,
            "iot": names.TEST_IOT,
        },
    ),
    SnippetStep(
        "openzaak-zaaktype-archief",
        ("openzaak",),
        "openzaak_zaaktype",
        None,
        {
            "domein": names.TEST_CATALOGUS_DOMEIN,
            "rsin": names.TEST_CATALOGUS_RSIN,
            "identificatie": names.ARCHIEF_ZAAKTYPE,
            "iot_omschrijving": names.ARCHIEF_IOT,
            "besluittype": names.ARCHIEF_BESLUITTYPE,
            "archief": True,
        },
    ),
    # A short-identificatie published zaaktype for ZaakBrug's ZDS (StUF code is at most 10 chars); only where
    # ZaakBrug runs. Same snippet, so unbootstrap deletes it and its zaken as for the klacht zaaktype.
    SnippetStep(
        "openzaak-zaaktype-zaakbrug",
        ("openzaak", "zaakbrug"),
        "openzaak_zaaktype",
        None,
        {
            "domein": names.TEST_CATALOGUS_DOMEIN,
            "rsin": names.TEST_CATALOGUS_RSIN,
            "identificatie": names.ZAAKBRUG_ZAAKTYPE,
            "iot_omschrijving": names.ZAAKBRUG_IOT,
            "besluittype": names.ZAAKBRUG_BESLUITTYPE,
        },
    ),
    # The zaaktype of podiumd-tests' BPMN process in ZAC (step zac-bpmn-process).
    ZacCatalogusStep(
        "openzaak-zaaktype-bpmn",
        ("openzaak", "zac", "keycloak"),
        "openzaak_zaaktype",
        None,
        {
            "domein": names.TEST_CATALOGUS_DOMEIN,
            "rsin": names.TEST_CATALOGUS_RSIN,
            "identificatie": names.BPMN_ZAAKTYPE,
            "iot_omschrijving": names.BPMN_IOT,
            "besluittype": names.BPMN_BESLUITTYPE,
            "statustypen": ["Ingediend", "In behandeling", HEROPEND, "Afgehandeld"],
        },
        admin=ADMIN,
    ),
    # The informatieobjecttype ZAC stores mails as; throwaway ZAC zaaktypen of the tests link it.
    SnippetStep(
        "openzaak-iot-email",
        ("openzaak",),
        "openzaak_iot",
        None,
        {"domein": names.TEST_CATALOGUS_DOMEIN, "rsin": names.TEST_CATALOGUS_RSIN, "omschrijving": names.EMAIL_IOT},
    ),
    # ZaakBrug's statuses on a zaak of an expired zaaktype version: version 1 valid in 2020, version 2 from 2021.
    SnippetStep(
        "openzaak-zaaktype-zaakbrug-versies",
        ("openzaak", "zaakbrug"),
        "openzaak_zaaktype",
        None,
        {
            "domein": names.TEST_CATALOGUS_DOMEIN,
            "rsin": names.TEST_CATALOGUS_RSIN,
            "identificatie": names.ZAAKBRUG_VERSIES_ZAAKTYPE,
            "iot_omschrijving": names.ZAAKBRUG_VERSIES_IOT,
            "besluittype": names.ZAAKBRUG_VERSIES_BESLUITTYPE,
            "versions": [["2020-01-01", "2020-12-31"], ["2021-01-01", None]],
        },
    ),
    # Platform wiring.
    OmcAbonnement(),
    SnippetStep(
        "openzaak-of-autorisatie",
        ("openzaak", "openformulieren"),
        "catalogus_autorisatie",
        "ptest_bootstrap_of_autorisatie_record",
        {"domein": names.TEST_CATALOGUS_DOMEIN, "rsin": names.TEST_CATALOGUS_RSIN},
        record=True,
        wiring=True,
        context_params=lambda ctx: {"client_id": ctx.env.profile.settings.get("zgw_client_id", "formulier")},
    ),
    SnippetStep(
        "openformulieren-zgw-group",
        ("openformulieren", "openzaak"),
        "openformulieren_zgw_group",
        None,
        {
            "prefix": names.PREFIX,
            "client_id": names.ZGW_CLIENT_ID,
            "domein": names.TEST_CATALOGUS_DOMEIN,
            "rsin": names.TEST_CATALOGUS_RSIN,
        },
        wiring=True,
        context_params=openformulieren_params,
    ),
    OF_REDACTEUR,
    SnippetStep(
        "openformulieren-form",
        ("openformulieren", "openzaak"),
        "openformulieren_form",
        None,
        {
            "slug": names.TEST_FORM,
            "components": TEST_FORM_COMPONENTS,
            "registration": ZGW_REGISTRATION,
            # Logins through Keycloak's mock (step openformulieren-oidc-mock).
            "auth_backends": ["digid_oidc", "eherkenning_oidc"],
            "settings": {},
        },
    ),
    # The payment tests' Ogone merchant; the tests sign as Ogone with its passphrase.
    SnippetStep(
        "openformulieren-ogone",
        ("openformulieren",),
        "openformulieren_ogone",
        names.OGONE_STORE_KEY,
        {
            "label": names.OGONE_MERCHANT,
            "pspid": names.PREFIX,
            "hash_algorithm": OGONE_HASH,
            "endpoint": OGONE_ENDPOINT,
        },
    ),
    # The Worldline merchant; its endpoint is the mock server (step infra-mock-server).
    SnippetStep(
        "openformulieren-worldline",
        ("openformulieren", "cluster"),
        "openformulieren_worldline",
        names.WORLDLINE_STORE_KEY,
        {"pspid": names.WORLDLINE_MERCHANT},
        context_params=lambda ctx: {"endpoint": mock_server_root(ctx.env)},
    ),
    # Register a submission only once it is paid (draaiboek OF-022), where the profile allows it.
    SnippetStep(
        "openformulieren-payment-wait",
        ("openformulieren",),
        "openformulieren_payment_wait",
        "ptest_bootstrap_of_payment_wait_record",
        record=True,
        wiring=True,
        opt_in="of_wait_for_payment",
    ),
    SnippetStep(
        "opennotificaties-kanalen",
        ("opennotificaties",),
        "kanalen",
        "ptest_bootstrap_kanalen_record",
        {"kanalen": names.KANALEN},
        record=True,
        wiring=True,
    ),
    # Users for KISS and ITA (TA kcc-medewerker), for the admin UIs, PABC and ZAC (TA testadmin),
    # and for the DigiD and eHerkenning logins through Keycloak (TA testinwoner, testinwoner2, testbedrijf).
    # Open Archiefbeheer role users (TA seed-oab-users: recordmanager-test, reviewer-test, ...);
    # OAB logs them in locally, as in podiumd-minikube.
    *(django_user_step("openarchiefbeheer", key, (group,)) for key, group in OAB_ROLES.items()),
    KeycloakRoles((KCC, ADMIN, ITA_BEHEERDER, *ZAC_ROLE_USERS.values())),
    KCC,
    ADMIN,
    ITA_BEHEERDER,
    *ZAC_ROLE_USERS.values(),
    OpenKlantActor("kcc"),
    ItaMedewerker(KCC),
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
                    "provider": f"{names.PREFIX}-digid",
                    "scopes": ["openid", "bsn"],
                    "options": {"identity_settings": {"bsn_claim_path": ["bsn"]}},
                },
                "oidc-eherkenning": {
                    "provider": f"{names.PREFIX}-eherkenning",
                    "scopes": ["openid", "eherkenning"],
                    "options": {"identity_settings": EHERKENNING_CLAIMS},
                },
            },
            "eherkenning_site": True,
            "accounts": [openinwoner_account(user) for user in IDENTITIES if "bsn" in user.attributes],
            "identities": [openinwoner_number(user) for user in IDENTITIES],
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
                    "provider": f"{names.PREFIX}-digid",
                    "scopes": ["openid", "bsn"],
                    "options": {"identity_settings": {"bsn_claim_path": ["bsn"]}, "loa_settings": OF_LOA},
                },
                "oidc-eherkenning": {
                    "provider": f"{names.PREFIX}-eherkenning",
                    "scopes": ["openid", "eherkenning"],
                    # The mock sends no acting subject; Open Formulieren needs it only in strict mode.
                    "options": {
                        "identity_settings": {**EHERKENNING_CLAIMS, "acting_subject_claim_path": ["acting_subject"]},
                        "loa_settings": OF_LOA,
                    },
                },
            },
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
        {
            "pages": OI_PAGES,
            "author": f"{names.PREFIX}-cms@example.invalid",
            "contact_email": "noreply@example.invalid",
        },
        record=True,
        wiring=True,
    ),
    OI_BEGELEIDER,
    # Wiring W4: Open Inwoner shows zaken through an API group (TA seed-oi-bedrading.sh).
    SnippetStep(
        "openinwoner-zgw-group",
        ("openinwoner", "openzaak"),
        "oi_zgw_group",
        "ptest_bootstrap_openinwoner_zgw_group_record",
        {"name": f"{names.PREFIX}-openzaak"},
        record=True,
        wiring=True,
        context_params=lambda ctx: {"zaken_url": f"{ctx.env.profile.urls['openzaak']}/zaken/api/v1/"},
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
            "group": f"{names.PREFIX}-openzaak",
            "domein": names.TEST_CATALOGUS_DOMEIN,
            "rsin": names.TEST_CATALOGUS_RSIN,
            "identificatie": names.TEST_ZAAKTYPE,
            "iot_omschrijving": names.TEST_IOT,
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
        names.OPENKLANT_OI_STORE_KEY,
        {"modules": ("openklant.components.token.models",), "identifier": names.OPENKLANT_OI_STORE_KEY},
        wiring=True,
    ),
    SnippetStep(
        "openinwoner-openklant",
        ("openinwoner", "openklant"),
        "oi_openklant",
        "ptest_bootstrap_openinwoner_openklant_record",
        {"subjects": ["Algemene vraag", "Vraag over zaak"], "group": f"{names.PREFIX}-openzaak"},
        record=True,
        wiring=True,
        context_params=openinwoner_openklant_params,
    ),
    OpenInwonerPartijen(),
    # ZAC's ontvangstbevestiging of productaanvragen, where the profile allows it (draaiboek OF-002).
    ZacParameters(ADMIN, "zac-email-confirmation", "zac_email_confirmation", EMAIL_CONFIRMATION),
    # ZAC's human task Aanvullende informatie for that zaaktype, where the profile allows it: the taken tests start it.
    ZacParameters(ADMIN, "zac-aanvullende-informatie", "zac_aanvullende_informatie", AANVULLENDE_INFORMATIE),
    # podiumd-tests' BPMN process in ZAC, for zaaktype ptest-bootstrap-bpmn (needs PABC to know that zaaktype).
    ZacBpmnProcess(ADMIN),
    # Productaanvragen of type ptest-bootstrap-bpmn-productaanvraag become zaken of that zaaktype.
    ZacBpmnProductaanvraag(ADMIN),
    # KISS's contactmoment kanalen, where the profile allows it (draaiboek KI-053-055).
    KissKanalen(ADMIN),
)
