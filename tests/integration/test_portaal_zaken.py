"""Chain: a zaak in Open Zaak shows in the inwoner's or company's Mijn zaken in Open Inwoner.

Ported from TA interaction 21, 31 and 141, regression 95 and 143. Open Inwoner reaches Open
Zaak through the API group of wiring W4 (no zaken cache), the pages are W5, the logins W1.
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.browser import browser_session
from podiumd_tests.openinwoner import portal_login
from podiumd_tests.openinwoner import refuse_cookies
from podiumd_tests.seed.openzaak import link_document
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import make_rol
from podiumd_tests.seed.openzaak import make_status
from podiumd_tests.seed.openzaak import make_zaak

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
    refuse_cookies(page)
    expect(page.get_by_text(str(zaak["identificatie"])).first).to_be_visible()


def test_bedrijfs_zaak_is_in_mijn_zaken(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
) -> None:
    """A zaak with the company as initiator is listed after an eHerkenning login (TA int-141)."""
    need_bootstrap(BEDRIJF.name, *WIRING)
    zaak = zaak_of(openzaak, registry, parts, kvkNummer=BEDRIJF.attributes["kvk"][0])
    portal_login(page, podiumd_env, "eherkenning", BEDRIJF, "/mijn-zaken/")
    refuse_cookies(page)
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
    refuse_cookies(page)
    page.locator(f'a[href*="{zaak["uuid"]}"]').first.click()
    expect(page.get_by_text(str(document["titel"])).first).to_be_visible()
    href = page.locator(f'a[href*="{str(document["url"]).rsplit("/", 1)[-1]}"]').first.get_attribute("href")
    assert href, "no download link for the document"
    download = browser_session(page, podiumd_env).get(
        re.sub(r"^/", podiumd_env.profile.urls["openinwoner"] + "/", href)
    )
    assert inhoud in download.text
