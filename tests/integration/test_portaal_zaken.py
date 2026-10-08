"""Chain: a zaak in Open Zaak shows in the inwoner's or company's Mijn zaken in Open Inwoner.

Ported from TA interaction 21, 31, 111, 141, 162 and 164, regression 61, 95, 123 and 143. Open Inwoner reaches
Open Zaak through the API group of wiring W4 (no zaken cache), the pages are W5, the logins W1;
upload and questions need the zaaktype configuration (bootstrap openinwoner-zaaktype-config).
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.browser import browser_session
from podiumd_tests.json_data import section
from podiumd_tests.openinwoner import portal_login
from podiumd_tests.openinwoner import upload_document
from podiumd_tests.openinwoner import virus_scan_enabled
from podiumd_tests.seed.openklant import delete_klantcontact_tree
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
# The EICAR anti-virus test file: every virus scanner reports it, it is no malware.
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
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


# Playwright's descriptors without default_browser_type: the suite runs Chromium.
PHONES = {
    "iPhone 13": {
        "viewport": {"width": 390, "height": 664},
        "device_scale_factor": 3,
        "is_mobile": True,
        "has_touch": True,
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15"
        " (KHTML, like Gecko) Version/26.6 Mobile/15E148 Safari/604.1",
    },
    "Pixel 5": {
        "viewport": {"width": 393, "height": 727},
        "device_scale_factor": 2.75,
        "is_mobile": True,
        "has_touch": True,
        "user_agent": "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko)"
        " Chrome/153.0.8010.12 Mobile Safari/537.36",
    },
}


@pytest.mark.parametrize(
    "phone", [pytest.param(name, marks=pytest.mark.browser_context_args(**args)) for name, args in PHONES.items()]
)
def test_mijn_zaken_on_a_phone(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
    phone: str,
) -> None:
    """On a phone, Mijn zaken lists the inwoner's zaak and fits the screen width (TA reg-61)."""
    need_bootstrap(INWONER.name, *WIRING)
    zaak = zaak_of(openzaak, registry, parts, inpBsn=INWONER.attributes["bsn"][0])
    portal_login(page, podiumd_env, "digid", INWONER, "/mijn-zaken/")
    expect(page.get_by_text(str(zaak["identificatie"])).first).to_be_visible()
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0, f"{phone}: page {overflow}px wider than the screen"


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
    upload_document(page, bestand, bestand.encode())
    found = wait_until(lambda: documents_of(openzaak, zaak), timeout=30, description=f"document {bestand} on the zaak")
    assert bestand in found


@pytest.mark.requires("cluster")
def test_infected_upload_is_refused(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
) -> None:
    """With ClamAV on, an upload of the EICAR test file does not reach the zaak (TA reg-123)."""
    if not virus_scan_enabled(podiumd_env):
        pytest.skip(
            "Open Inwoner scans no uploads: set profile setting clamav and run bootstrap step openinwoner-virus-scan"
        )
    need_bootstrap(INWONER.name, *WIRING, "openinwoner-zaaktype-config")
    zaak = zaak_of(openzaak, registry, parts, inpBsn=INWONER.attributes["bsn"][0])
    clean_up_new_documents(openzaak, registry, zaak)
    portal_login(page, podiumd_env, "digid", INWONER, "/mijn-zaken/")
    page.locator(f'a[href*="{zaak["uuid"]}"]').first.click()
    upload_document(page, f"{registry.tagged('eicar')}.txt", EICAR)
    assert documents_of(openzaak, zaak) == []


def documents_of(openzaak: ApiClient, zaak: JsonObject) -> list[str]:
    """The file names of the zaak's documents."""
    links = openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": str(zaak["url"])})
    return [str(openzaak.get(str(link["informatieobject"])).get("bestandsnaam")) for link in links]


@pytest.mark.core
def test_question_about_a_zaak_reaches_open_klant(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    openklant: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
) -> None:
    """A question asked on the zaak's status page becomes a klantcontact about the zaak (TA int-164)."""
    need_bootstrap(INWONER.name, *WIRING, "openinwoner-zaaktype-config", "openinwoner-openklant")
    zaak = zaak_of(openzaak, registry, parts, inpBsn=INWONER.attributes["bsn"][0])
    about = {"onderwerpobjectidentificatorObjectId": str(zaak["uuid"])}

    def klantcontacten() -> list[str]:
        return [str(section(o, "klantcontact")["url"]) for o in openklant.list("onderwerpobjecten", about)]

    registry.add(
        f"questions about zaak {zaak['uuid']}",
        lambda: [delete_klantcontact_tree(openklant, k) for k in klantcontacten()],
    )
    vraag = registry.tagged("zaakvraag")
    portal_login(page, podiumd_env, "digid", INWONER, "/mijn-zaken/")
    page.locator(f'a[href*="{zaak["uuid"]}"]').first.click()
    page.locator('#contact-form textarea[name="question"]').fill(vraag)
    page.locator("#submit_contact").click()
    found = wait_until(klantcontacten, timeout=30, description=f"klantcontact about zaak {zaak['uuid']}")
    # Open Inwoner appends "Case number: <identificatie>" to the question.
    inhoud = [str(openklant.get(k).get("inhoud")) for k in found]
    assert len(inhoud) == 1
    assert inhoud[0].startswith(vraag)
    assert str(zaak["identificatie"]) in inhoud[0]
