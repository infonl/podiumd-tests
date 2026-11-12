"""Bootstrap step: podiumd-tests' BPMN process in ZAC, for the zaaktype of step openzaak-zaaktype-bpmn.

ZAC (5.9) starts a BPMN process for a zaaktype with a zaaktype-bpmn-configuration; the process and its form.io
forms are uploaded through ZAC's admin API, as ZAC's own integration tests do. ZAC asks PABC for the user's rights
on the zaaktype by the user's realm roles: the step maps the functional roles ZAC_FUNCTIONAL_ROLES (realm roles
of the test admin and the ZAC role users) to ZAC's application roles in PABC domain ptest-bootstrap, which holds
only this zaaktype, so the rights do not depend on the estate's PABC dataset.
"""

from __future__ import annotations

import io
import zipfile

from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

from podiumd_tests.bootstrap.names import BPMN_PRODUCTAANVRAAGTYPE
from podiumd_tests.bootstrap.names import BPMN_ZAAKTYPE
from podiumd_tests.bootstrap.names import PREFIX
from podiumd_tests.bootstrap.names import ZAC_DOMAIN
from podiumd_tests.bootstrap.names import ZAC_FUNCTIONAL_ROLES
from podiumd_tests.bootstrap.names import ZGW_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_STORE_KEY
from podiumd_tests.clients.platform import openzaak_client
from podiumd_tests.json_data import entries
from podiumd_tests.pabc import add_zaaktype_entity_type
from podiumd_tests.pabc import admin_session
from podiumd_tests.pabc import application_roles
from podiumd_tests.pabc import delete_entity_type
from podiumd_tests.pabc import delete_roles_and_domain
from podiumd_tests.pabc import domain_mappings
from podiumd_tests.pabc import ensure_domain
from podiumd_tests.pabc import ensure_functional_role
from podiumd_tests.pabc import zaaktype_entity_type
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import published_zaaktype
from podiumd_tests.zac import complete_task
from podiumd_tests.zac import open_task
from podiumd_tests.zac import user_groups
from podiumd_tests.zac import zac_session

if TYPE_CHECKING:
    from collections.abc import Mapping

    import requests

    from podiumd_tests.bootstrap.keycloak import KeycloakUser
    from podiumd_tests.bootstrap.runner import Context
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject

PROCESS_KEY = "ptestBpmnProcess"
# The process's tasks (bpmn/ptestBpmnProcess.bpmn).
INTAKE, SELECT = "Intake", "Select documents to sign"
SIGN, SUMMARY = "Sign the selected documents", "Summary"
ZAC_APPLICATION = "zaakafhandelcomponent"
FILES = Path(__file__).parent.parent / "bpmn"
DEFINITIONS = "/rest/bpmn-process-definitions"
CONFIGURATION = "/rest/zaaktype-bpmn-configuration"
# The BPMN test zaaktype's last statustype, and its resultaattype.
EINDSTATUS = "Afgehandeld"
# The statustype the process sets after the intake.
IN_BEHANDELING = "In behandeling"
# Intake form fields: the process mails MAIL_To with this vertrouwelijkheidaanduiding when MAIL_To is not empty.
MAIL_TO, MAIL_VERTROUWELIJKHEID = "MAIL_To", "MAIL_Vertrouwelijkheidaanduiding"


def complete_intake(
    http: requests.Session, zac_url: str, zaak: JsonObject, to: tuple[str, str], **fields: object
) -> None:
    """Complete the process's intake: assign the zaak to (group, behandelaar), with EINDSTATUS as status and resultaat.

    fields: more form data, which ZAC keeps as zaakdata.
    """
    groep, behandelaar = to
    data = {
        "AM_TeamBehandelaar_Groep": groep,
        "AM_TeamBehandelaar_Medewerker": behandelaar,
        "ZK_Status": EINDSTATUS,
        "ZK_Result": EINDSTATUS,
        **fields,
    }
    complete_task(http, zac_url, open_task(http, zac_url, str(zaak["uuid"]), INTAKE), data)


def process_files() -> dict[str, str]:
    """Return podiumd-tests' process and its forms by file name, as ZAC's download names them."""
    paths = [FILES / f"{PROCESS_KEY}.bpmn", *sorted(FILES.glob("*.json"))]
    return {path.name: path.read_text(encoding="utf-8") for path in paths}


def deploy_process(http: requests.Session, zac: str, key: str, files: Mapping[str, str]) -> None:
    """Deploy the .bpmn of files as the process's next version, then its .json forms for that version."""
    for name, content in files.items():
        if name.endswith(".bpmn"):
            body = {"filename": name, "content": content}
            expect_status(http.post(zac + DEFINITIONS, json=body), HTTPStatus.CREATED)
    for name, content in files.items():
        if name.endswith(".json"):
            body = {"filename": name, "content": content}
            expect_status(http.post(f"{zac}{DEFINITIONS}/{key}/forms", json=body), HTTPStatus.CREATED)


def deployed_files(http: requests.Session, zac: str, key: str) -> dict[str, str] | None:
    """Return the files of the process's latest version by path, from ZAC's ZIP download; None before ZAC 5.9."""
    response = http.get(f"{zac}{DEFINITIONS}/{key}/download")
    if response.status_code == HTTPStatus.NOT_FOUND:
        return None
    with zipfile.ZipFile(io.BytesIO(expect_status(response, HTTPStatus.OK).content)) as archive:
        return {name: archive.read(name).decode() for name in archive.namelist()}


def mappable_roles(pabc: requests.Session, pabc_url: str) -> dict[str, tuple[str, ...]]:
    """ZAC_FUNCTIONAL_ROLES whose application roles PABC has; podiumd chart 4.9's dataset lacks brp_zoeken."""
    known = {str(role.get("name")) for role in application_roles(pabc, pabc_url, ZAC_APPLICATION)}
    return {name: roles for name, roles in ZAC_FUNCTIONAL_ROLES.items() if set(roles) <= known}


def uuid_of(url: object) -> str:
    """Return the last path part of a ZGW resource URL."""
    return str(url).rstrip("/").rsplit("/", 1)[-1]


def bpmn_link(http: requests.Session, zac: str, zaaktype: str) -> JsonObject | None:
    """ZAC's link of process PROCESS_KEY to the zaaktype (uuid), its zaaktype-bpmn-configuration; None without one."""
    links = entries(expect_status(http.get(zac + CONFIGURATION), HTTPStatus.OK).json())
    mine = (link for link in links if link.get("bpmnProcessDefinitionKey") == PROCESS_KEY)
    return next((link for link in mine if link.get("zaaktypeUuid") == zaaktype), None)


@dataclass(frozen=True)
class ZacBpmnProcess:
    """The process ptestBpmnProcess with its forms, linked to the BPMN test zaaktype, which PABC knows.

    ZAC 5.9 has no call to delete a zaaktype-bpmn-configuration: remove leaves it, and names it in a note. The link
    has no productaanvraagtype and no niet-ontvankelijk resultaattype, so a link left for a deleted zaaktype neither
    blocks the next one nor breaks ZAC's list of links, which reads that resultaattype from Open Zaak.
    """

    admin: KeycloakUser
    name: str = "zac-bpmn-process"
    requires: tuple[str, ...] = ("zac", "openzaak", "pabc", "keycloak")
    wiring: bool = False

    def is_present(self, ctx: Context, /) -> bool:
        """Return whether the process is deployed as in FILES, linked to the BPMN zaaktype, and PABC maps the roles.

        A changed process or form makes apply deploy a new version; zaken started before keep the old one.
        """
        try:
            zaaktype = uuid_of(published_zaaktype(_openzaak(ctx), BPMN_ZAAKTYPE, "openzaak-zaaktype-bpmn")["url"])
        except LookupError:
            return False
        http, zac = self._zac(ctx)
        definitions = entries(expect_status(http.get(zac + DEFINITIONS), HTTPStatus.OK).json())
        keys = {definition.get("key") for definition in definitions}
        link = bpmn_link(http, zac, zaaktype)
        if PROCESS_KEY not in keys or link is None or link.get("zaakNietOntvankelijkResultaattype"):
            return False
        deployed = deployed_files(http, zac, PROCESS_KEY)
        if deployed is not None and deployed != process_files():
            return False
        pabc, pabc_url = self._pabc(ctx)
        wanted = mappable_roles(pabc, pabc_url).items()
        return all(domain_mappings(pabc, pabc_url, name) >= len(roles) for name, roles in wanted)

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Map the functional roles in PABC, deploy the process and its forms, and link it to the zaaktype."""
        zaaktype = published_zaaktype(_openzaak(ctx), BPMN_ZAAKTYPE, "openzaak-zaaktype-bpmn")
        self._map_roles(ctx, str(zaaktype["omschrijving"]))
        http, zac = self._zac(ctx)
        deploy_process(http, zac, PROCESS_KEY, process_files())
        expect_status(http.post(zac + CONFIGURATION, json=self.configuration(http, zac, zaaktype)), HTTPStatus.OK)
        return {}

    def configuration(self, http: requests.Session, zac: str, zaaktype: JsonObject) -> JsonObject:
        """ZAC's zaaktype-bpmn-configuration request for the zaaktype."""
        return {
            "zaaktypeUuid": uuid_of(zaaktype["url"]),
            "zaaktypeOmschrijving": zaaktype["omschrijving"],
            "bpmnProcessDefinitionKey": PROCESS_KEY,
            "groepNaam": user_groups(http, zac)[0],
            "defaultBehandelaarId": self.admin.username,
            "betrokkeneKoppelingen": {"brpKoppelen": True, "kvkKoppelen": True},
            "brpDoelbindingen": {
                "zoekWaarde": "BRPACT-ZoekenAlgemeen",
                "raadpleegWaarde": "BRPACT-AlgemeneTaken",
                "verwerkingregisterWaarde": "Algemeen",
            },
            "zaakbeeindigParameters": [],
        }

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Delete the forms, the process, PABC's functional roles, domain and entity type; the zaaktype link stays."""
        http, zac = self._zac(ctx)
        for form in sorted(FILES.glob("*.json")):
            http.delete(f"{zac}{DEFINITIONS}/{PROCESS_KEY}/forms/{form.stem}")
        deleted = http.delete(f"{zac}{DEFINITIONS}/{PROCESS_KEY}")
        if deleted.status_code not in {HTTPStatus.OK, HTTPStatus.NO_CONTENT, HTTPStatus.NOT_FOUND}:
            ctx.notes.append(f"process {PROCESS_KEY} not deleted: HTTP {deleted.status_code}")
        ctx.notes.append(f"zaaktype-bpmn-configuration of {BPMN_ZAAKTYPE} stays: ZAC 5.9 has no call to delete it")
        pabc, pabc_url = self._pabc(ctx)
        delete_roles_and_domain(pabc, pabc_url, ZAC_FUNCTIONAL_ROLES, ZAC_DOMAIN)
        entity_type = zaaktype_entity_type(pabc, pabc_url, BPMN_ZAAKTYPE)
        if entity_type is not None:
            delete_entity_type(pabc, pabc_url, entity_type)
        return ()

    def _zac(self, ctx: Context) -> tuple[requests.Session, str]:
        return _zac_login(ctx, self.admin)

    def _pabc(self, ctx: Context) -> tuple[requests.Session, str]:
        password = ctx.env.credentials.get(self.admin.store_key)
        return admin_session(ctx.env, self.admin.username, password), ctx.env.profile.urls["pabc"]

    def _map_roles(self, ctx: Context, omschrijving: str) -> None:
        """Map the functional roles PABC can map to their application roles in domain ZAC_DOMAIN of the zaaktype."""
        pabc, pabc_url = self._pabc(ctx)
        entity_type = zaaktype_entity_type(pabc, pabc_url, omschrijving)
        if entity_type is None:
            entity_type = add_zaaktype_entity_type(pabc, pabc_url, omschrijving)
        domain = ensure_domain(pabc, pabc_url, ZAC_DOMAIN, [entity_type])
        wanted = mappable_roles(pabc, pabc_url)
        for name, roles in wanted.items():
            ensure_functional_role(pabc, pabc_url, name, ZAC_APPLICATION, roles, domain)
        left_out = sorted(set(ZAC_FUNCTIONAL_ROLES) - set(wanted))
        if left_out:
            ctx.notes.append(f"not mapped, PABC lacks their application roles: {', '.join(left_out)}")


@dataclass(frozen=True)
class ZacBpmnProductaanvraag:
    """Productaanvraagtype BPMN_PRODUCTAANVRAAGTYPE on the zaaktype link of step zac-bpmn-process.

    ZAC then starts a zaak of the BPMN test zaaktype for such a productaanvraag. remove clears it: ZAC refuses a
    productaanvraagtype that a link left for a deleted zaaktype still holds.
    """

    admin: KeycloakUser
    name: str = "zac-bpmn-productaanvraag"
    requires: tuple[str, ...] = ("zac", "openzaak")
    wiring: bool = False

    def is_present(self, ctx: Context, /) -> bool:
        """Return whether the link of the BPMN test zaaktype has the productaanvraagtype."""
        link = self._link(ctx)
        return link is not None and link.get("productaanvraagtype") == BPMN_PRODUCTAANVRAAGTYPE

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Set the productaanvraagtype on the link; LookupError without the link."""
        link = self._link(ctx)
        if link is None:
            msg = f"ZAC has no link of process {PROCESS_KEY} to {BPMN_ZAAKTYPE}: bootstrap step zac-bpmn-process"
            raise LookupError(msg)
        self._store(ctx, {**link, "productaanvraagtype": BPMN_PRODUCTAANVRAAGTYPE})
        return {}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Clear the productaanvraagtype of the link."""
        link = self._link(ctx)
        if link is not None and link.get("productaanvraagtype") == BPMN_PRODUCTAANVRAAGTYPE:
            self._store(ctx, {**link, "productaanvraagtype": None})
        return ()

    def _link(self, ctx: Context) -> JsonObject | None:
        try:
            zaaktype = uuid_of(published_zaaktype(_openzaak(ctx), BPMN_ZAAKTYPE, "openzaak-zaaktype-bpmn")["url"])
        except LookupError:
            return None
        http, zac = _zac_login(ctx, self.admin)
        return bpmn_link(http, zac, zaaktype)

    def _store(self, ctx: Context, link: JsonObject) -> None:
        http, zac = _zac_login(ctx, self.admin)
        expect_status(http.post(zac + CONFIGURATION, json=link), HTTPStatus.OK)


def _zac_login(ctx: Context, admin: KeycloakUser) -> tuple[requests.Session, str]:
    password = ctx.env.credentials.get(admin.store_key)
    return zac_session(ctx.env, admin.username, password), ctx.env.profile.urls["zac"]


def _openzaak(ctx: Context) -> ApiClient:
    return openzaak_client(ctx.env, ZGW_CLIENT_ID, ZGW_STORE_KEY, PREFIX)
