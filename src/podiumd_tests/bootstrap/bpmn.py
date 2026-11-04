"""Bootstrap step: podiumd-tests' BPMN process in ZAC, for the zaaktype of step openzaak-zaaktype-bpmn.

ZAC (5.9) starts a BPMN process for a zaaktype with a zaaktype-bpmn-configuration; the process and its form.io
forms are uploaded through ZAC's admin API, as ZAC's own integration tests do. ZAC asks PABC for the user's rights
on the zaaktype by the user's realm roles: the step gives the test admin's realm role ptest-bootstrap-zac
ZAC's behandelaar and coordinator roles in PABC domain ptest-bootstrap, which holds only this zaaktype, so the
rights do not depend on the estate's PABC dataset.
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

from podiumd_tests.bootstrap.names import BPMN_ZAAKTYPE
from podiumd_tests.bootstrap.names import PREFIX
from podiumd_tests.bootstrap.names import ZAC_APPLICATION_ROLES
from podiumd_tests.bootstrap.names import ZAC_DOMAIN
from podiumd_tests.bootstrap.names import ZAC_FUNCTIONAL_ROLE
from podiumd_tests.bootstrap.names import ZGW_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_STORE_KEY
from podiumd_tests.clients.platform import openzaak_client
from podiumd_tests.json_data import entries
from podiumd_tests.pabc import add_zaaktype_entity_type
from podiumd_tests.pabc import admin_session
from podiumd_tests.pabc import delete_entity_type
from podiumd_tests.pabc import delete_functional_role_and_domain
from podiumd_tests.pabc import domain_mappings
from podiumd_tests.pabc import ensure_domain
from podiumd_tests.pabc import ensure_functional_role
from podiumd_tests.pabc import zaaktype_entity_type
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.zac import user_groups
from podiumd_tests.zac import zac_session

if TYPE_CHECKING:
    import requests

    from podiumd_tests.bootstrap import Context
    from podiumd_tests.bootstrap.keycloak import KeycloakUser
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject

PROCESS_KEY = "ptestBpmnProcess"
FILES = Path(__file__).parent.parent / "bpmn"
DEFINITIONS = "/rest/bpmn-process-definitions"
CONFIGURATION = "/rest/zaaktype-bpmn-configuration"


def bpmn_zaaktype(openzaak: ApiClient) -> JsonObject:
    """The published zaaktype of step openzaak-zaaktype-bpmn, as Open Zaak's Catalogi API shows it."""
    found = [
        z for z in openzaak.list(f"{CATALOGI}/zaaktypen", {"identificatie": BPMN_ZAAKTYPE}) if not z.get("concept")
    ]
    if not found:
        msg = f"zaaktype {BPMN_ZAAKTYPE} missing: bootstrap step openzaak-zaaktype-bpmn"
        raise LookupError(msg)
    return found[0]


def uuid_of(url: object) -> str:
    """The last path part of a ZGW resource URL."""
    return str(url).rstrip("/").rsplit("/", 1)[-1]


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

    def _zac(self, ctx: Context) -> tuple[requests.Session, str]:
        password = ctx.env.credentials.get(self.admin.store_key)
        return zac_session(ctx.env, self.admin.username, password), ctx.env.profile.urls["zac"]

    @staticmethod
    def _openzaak(ctx: Context) -> ApiClient:
        return openzaak_client(ctx.env, ZGW_CLIENT_ID, ZGW_STORE_KEY, PREFIX)

    def _pabc(self, ctx: Context) -> tuple[requests.Session, str]:
        password = ctx.env.credentials.get(self.admin.store_key)
        return admin_session(ctx.env, self.admin.username, password), ctx.env.profile.urls["pabc"]

    def is_present(self, ctx: Context, /) -> bool:
        """The process is deployed and linked to the current BPMN test zaaktype, and PABC maps the role."""
        try:
            zaaktype = uuid_of(bpmn_zaaktype(self._openzaak(ctx))["url"])
        except LookupError:
            return False
        http, zac = self._zac(ctx)
        keys = {d.get("key") for d in entries(expect_status(http.get(zac + DEFINITIONS), HTTPStatus.OK).json())}
        links = entries(expect_status(http.get(zac + CONFIGURATION), HTTPStatus.OK).json())
        linked = any(
            c.get("bpmnProcessDefinitionKey") == PROCESS_KEY
            and c.get("zaaktypeUuid") == zaaktype
            and not c.get("zaakNietOntvankelijkResultaattype")
            for c in links
        )
        if PROCESS_KEY not in keys or not linked:
            return False
        pabc, pabc_url = self._pabc(ctx)
        return domain_mappings(pabc, pabc_url, ZAC_FUNCTIONAL_ROLE) >= len(ZAC_APPLICATION_ROLES)

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Give the test admin rights in PABC, deploy the process and its forms, and link it to the zaaktype."""
        openzaak = self._openzaak(ctx)
        zaaktype = bpmn_zaaktype(openzaak)
        pabc, pabc_url = self._pabc(ctx)
        entity_type = zaaktype_entity_type(pabc, pabc_url, str(zaaktype["omschrijving"]))
        if entity_type is None:
            entity_type = add_zaaktype_entity_type(pabc, pabc_url, str(zaaktype["omschrijving"]))
        domain = ensure_domain(pabc, pabc_url, ZAC_DOMAIN, [entity_type])
        ensure_functional_role(
            pabc, pabc_url, ZAC_FUNCTIONAL_ROLE, "zaakafhandelcomponent", ZAC_APPLICATION_ROLES, domain
        )
        http, zac = self._zac(ctx)
        process = FILES / f"{PROCESS_KEY}.bpmn"
        body = {"filename": process.name, "content": process.read_text(encoding="utf-8")}
        expect_status(http.post(zac + DEFINITIONS, json=body), HTTPStatus.CREATED)
        for form in sorted(FILES.glob("*.json")):
            body = {"filename": form.name, "content": form.read_text(encoding="utf-8")}
            expect_status(http.post(f"{zac}{DEFINITIONS}/{PROCESS_KEY}/forms", json=body), HTTPStatus.CREATED)
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
        """Delete the forms, the process, PABC's functional role, domain and entity type; the zaaktype link stays."""
        http, zac = self._zac(ctx)
        for form in sorted(FILES.glob("*.json")):
            http.delete(f"{zac}{DEFINITIONS}/{PROCESS_KEY}/forms/{form.stem}")
        deleted = http.delete(f"{zac}{DEFINITIONS}/{PROCESS_KEY}")
        if deleted.status_code not in {HTTPStatus.OK, HTTPStatus.NO_CONTENT, HTTPStatus.NOT_FOUND}:
            ctx.notes.append(f"process {PROCESS_KEY} not deleted: HTTP {deleted.status_code}")
        ctx.notes.append(f"zaaktype-bpmn-configuration of {BPMN_ZAAKTYPE} stays: ZAC 5.9 has no call to delete it")
        pabc, pabc_url = self._pabc(ctx)
        delete_functional_role_and_domain(pabc, pabc_url, ZAC_FUNCTIONAL_ROLE, ZAC_DOMAIN)
        entity_type = zaaktype_entity_type(pabc, pabc_url, BPMN_ZAAKTYPE)
        if entity_type is not None:
            delete_entity_type(pabc, pabc_url, entity_type)
        return ()
