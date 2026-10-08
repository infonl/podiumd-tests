"""Chain: a zaak in Open Zaak shows in the inwoner's or company's Mijn zaken in Open Inwoner.

Ported from TA interaction 21, 31, 111, 141 and 162, regression 95 and 143. Open Inwoner reaches
Open Zaak through the API group of wiring W4 (no zaken cache), the pages are W5, the logins W1;
upload needs the zaaktype configuration (bootstrap openinwoner-zaaktype-config).
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.browser import browser_session
from podiumd_tests.openinwoner import portal_login
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import clean_up_new_documents
from podiumd_tests.seed.openzaak import link_document
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import make_rol
from podiumd_tests.seed.openzaak import make_status
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.sync_api import Page

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.ui,
    pytest.mark.requires("openinwoner", "openzaak", "keycloak"),
]

INWONER, _, BEDRIJF = IDENTITIES
WIRING = ("openinwoner-oidc-mock", "openinwoner-cms-pages", "openinwoner-zgw-group")


def zaak_of(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts, **betrokkene: object) -> JsonObject:
    """An openbaar zaak with its first status (Open Inwoner hides zaken without one) and this initiator."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    soort = "natuurlijk_persoon" if "inpBsn" in betrokkene else "niet_natuurlijk_persoon"
    make_rol(openzaak, registry, zaak, parts.roltypen["initiator"], soort, **betrokkene)
    make_status(openzaak, zaak, str(parts.statustypen[0]["url"]))
    return zaak


@pytest.mark.core
def test_inwoners_zaak_is_in_mijn_zaken(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
) -> None:
    """A zaak with the inwoner as initiator is listed in Mijn zaken (TA int-21, reg-95)."""
    need_bootstrap(INWONER.name, *WIRING)
    zaak = zaak_of(openzaak, registry, parts, inpBsn=INWONER.attributes["bsn"][0])
    portal_login(page, podiumd_env, "digid", INWONER, "/mijn-zaken/")
    expect(page.get_by_text(str(zaak["identificatie"])).first).to_be_visible()


def test_bedrijfs_zaak_is_in_mijn_zaken(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
) -> None:
    """A zaak of the company's vestiging is listed after an eHerkenning login (TA int-141)."""
    need_bootstrap(BEDRIJF.name, *WIRING)
    # The login carries the vestiging, and Open Inwoner filters on it too.
    vestiging = BEDRIJF.attributes["vestigingsnummer"][0]
    zaak = zaak_of(openzaak, registry, parts, kvkNummer=BEDRIJF.attributes["kvk"][0], vestigingsNummer=vestiging)
    portal_login(page, podiumd_env, "eherkenning", BEDRIJF, "/mijn-zaken/")
    expect(page.get_by_text(str(zaak["identificatie"])).first).to_be_visible()


def test_zaak_document_can_be_downloaded(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
) -> None:
    """A definitief document of the zaak is on its status page and downloads with its content (TA int-31, reg-143)."""
    need_bootstrap(INWONER.name, *WIRING)
    zaak = zaak_of(openzaak, registry, parts, inpBsn=INWONER.attributes["bsn"][0])
    inhoud = registry.tagged("documentinhoud")
    document = make_document(openzaak, registry, parts.informatieobjecttype, inhoud, status="definitief")
    link_document(openzaak, registry, zaak, document)
    portal_login(page, podiumd_env, "digid", INWONER, "/mijn-zaken/")
    page.locator(f'a[href*="{zaak["uuid"]}"]').first.click()
    expect(page.get_by_text(str(document["titel"])).first).to_be_visible()
    href = page.locator(f'a[href*="{str(document["url"]).rsplit("/", 1)[-1]}"]').first.get_attribute("href")
    assert href, "no download link for the document"
    download = browser_session(page, podiumd_env).get(
        re.sub(r"^/", podiumd_env.profile.urls["openinwoner"] + "/", href)
    )
    assert inhoud in download.text


@pytest.mark.core
def test_uploaded_document_reaches_the_zaak(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
) -> None:
    """A file uploaded on the zaak's status page becomes a document of the zaak (TA int-111, int-162)."""
    need_bootstrap(INWONER.name, *WIRING, "openinwoner-zaaktype-config")
    zaak = zaak_of(openzaak, registry, parts, inpBsn=INWONER.attributes["bsn"][0])
    clean_up_new_documents(openzaak, registry, zaak)
    bestand = f"{registry.tagged('upload')}.txt"
    portal_login(page, podiumd_env, "digid", INWONER, "/mijn-zaken/")
    page.locator(f'a[href*="{zaak["uuid"]}"]').first.click()
    upload = page.locator("#document-upload")
    upload.locator('input[name="file"]').set_input_files(
        files=[{"name": bestand, "mimeType": "text/plain", "buffer": bestand.encode()}]
    )
    upload.get_by_role("button", name="Upload documenten").click()

    def uploaded() -> list[str]:
        links = openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": str(zaak["url"])})
        return [str(openzaak.get(str(link["informatieobject"])).get("bestandsnaam")) for link in links]

    assert bestand in wait_until(uploaded, timeout=30, description=f"document {bestand} on the zaak")
