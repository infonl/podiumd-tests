"""Chain: a zaak in Open Zaak shows in the inwoner's or company's Mijn zaken in Open Inwoner.

Ported from TA interaction 21, 31, 111, 141, 162 and 164, regression 61, 95, 123 and 143. Open Inwoner reaches
Open Zaak through the API group of wiring W4 (no zaken cache), the pages are W5, the logins W1;
upload and questions need the zaaktype configuration (bootstrap openinwoner-zaaktype-config).
"""

from __future__ import annotations

import re

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.bootstrap.bpmn import complete_intake
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.browser import browser_session
from podiumd_tests.json_data import section
from podiumd_tests.mailpit import received_message
from podiumd_tests.openinwoner import LOGINS
from podiumd_tests.openinwoner import choose_document
from podiumd_tests.openinwoner import is_virus_scan_enabled
from podiumd_tests.openinwoner import portal_login
from podiumd_tests.openinwoner import upload_document
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openklant import delete_klantcontact_tree
from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import clean_up_new_documents
from podiumd_tests.seed.openzaak import link_document
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import make_rol
from podiumd_tests.seed.openzaak import make_status
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import send_mail
from podiumd_tests.zac_betrokkenen import make_person_initiator
from podiumd_tests.zac_documents import zaak_documents

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

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
LIST_TIMEOUT_MS = 30_000
MAIL_TIMEOUT = 60
WIRING = ("openinwoner-oidc-mock", "openinwoner-cms-pages", "openinwoner-zgw-group")


# The company parameter of tests that open a zaak's detail.
WHO = [
    "inwoner",
    pytest.param(
        "bedrijf",
        marks=pytest.mark.xfail(
            strict=True,
            reason="[open-inwoner-2] Open Inwoner 2.4.3 and 2.5.0: with fetch_eherkenning_zaken_with_openzaak_120_params Mijn zaken lists"
            " a zaak by nietNatuurlijkPersoon.vestigingsNummer, but its detail accepts only a vestiging rol"
            " (fetch_roles_for_zaak_and_vestigingsnummer) and answers 404; not yet reported upstream",
        ),
    ),
]


@pytest.fixture(scope="module", name="virus_scan")
def fixture_virus_scan(podiumd_env: Environment) -> None:
    """Skips unless Open Inwoner scans uploads with ClamAV."""
    if not is_virus_scan_enabled(podiumd_env):
        pytest.skip(
            "Open Inwoner scans no uploads: set profile setting clamav and run bootstrap step openinwoner-virus-scan"
        )


def zaak_of(
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    who: str = "inwoner",
    generiek: str = "initiator",
    machtiging: str = "",
) -> JsonObject:
    """An openbaar zaak with its first status (Open Inwoner hides zaken without one) and the identity as initiator.

    generiek and machtiging: the omschrijvingGeneriek of the identity's roltype and its indicatieMachtiging.
    """
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    attributes = LOGINS[who][0].attributes
    roltype = parts.roltypen[generiek]
    if who == "inwoner":
        make_rol(openzaak, registry, zaak, roltype, "natuurlijk_persoon", machtiging, inpBsn=attributes["bsn"][0])
    else:
        # The login carries the vestiging, and Open Inwoner filters on it too.
        vestiging = {"kvkNummer": attributes["kvk"][0], "vestigingsNummer": attributes["vestigingsnummer"][0]}
        make_rol(openzaak, registry, zaak, roltype, "niet_natuurlijk_persoon", machtiging, **vestiging)
    make_status(openzaak, zaak, str(parts.statustypen[0]["url"]))
    return zaak


def log_in(page: Page, podiumd_env: Environment, who: str = "inwoner") -> None:
    """Log the identity in; the page ends on Mijn zaken."""
    identity, method = LOGINS[who]
    portal_login(page, podiumd_env, method, identity, "/mijn-zaken/")


# Search can be switched off by test_portaal_zoeken; it runs on the same worker.
@pytest.mark.xdist_group("openinwoner-search")
@pytest.mark.tc("OI-091")
@pytest.mark.source("draaiboek OI-091", "The portal can be searched on zaaknummer.")
@pytest.mark.scenario("""
    Given an inwoner with a zaak in Open Zaak is logged in to Open Inwoner
    When the inwoner searches on the zaaknummer
    Then the portal opens that zaak
""")
def test_search_on_a_zaaknummer_opens_the_zaak(
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
) -> None:
    """A logged-in inwoner who searches on the number of one of their zaken lands on that zaak."""
    need_bootstrap(INWONER.name, *WIRING, "openinwoner-cms-pages")
    zaak = zaak_of(openzaak, registry, parts)
    log_in(page, podiumd_env)
    page.goto(f"{podiumd_env.profile.urls['openinwoner']}/search/?query={zaak['identificatie']}")
    expect(page).to_have_url(re.compile(str(zaak["uuid"])))


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
    "screen",
    [
        pytest.param("desktop", marks=pytest.mark.core),
        *(pytest.param(name, marks=pytest.mark.browser_context_args(**args)) for name, args in PHONES.items()),
    ],
)
@pytest.mark.source(
    "TA interaction/21-portaal-mijn-zaken-ui.spec.ts",
    "A logged-in inwoner sees their own zaak on the portal's Mijn zaken.",
)
@pytest.mark.source(
    "TA regression/95-portaal-filtering.spec.ts",
    "Mijn zaken and its content endpoint load for a DigiD-logged-in inwoner.",
)
@pytest.mark.source(
    "TA regression/61-mobile-mijn-zaken.spec.ts",
    "Mijn zaken renders correctly on mobile viewports (iPhone 13, Pixel 5).",
)
@pytest.mark.source(
    "TA regression/110-portaal-anoniem-en-mobile.spec.ts", "A citizen can use the zaken overview in the mobile view."
)
@pytest.mark.source(
    "TA interaction/10-cross-component-zaak-portaal.spec.ts",
    "A zaak with the inwoner's BSN as initiator is found by the rol filter the portal uses.",
)
@pytest.mark.scenario("""
    Given an inwoner with a zaak in Open Zaak
    When the inwoner logs in to Open Inwoner with DigiD on a desktop or phone screen
    Then Mijn zaken lists the zaak
    And the page fits the width of the screen
""")
def test_inwoners_zaak_is_in_mijn_zaken(
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
    screen: str,
) -> None:
    """Mijn zaken lists a zaak with the inwoner as initiator and fits the screen width (TA int-21, reg-95, 61)."""
    need_bootstrap(INWONER.name, *WIRING)
    zaak = zaak_of(openzaak, registry, parts)
    log_in(page, podiumd_env)
    expect_listed(page, zaak)
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0, f"{screen}: page {overflow}px wider than the screen"


@pytest.mark.source(
    "TA interaction/141-bedrijf-eherkenning-mijn-zaken.spec.ts",
    "After an eHerkenning login a company sees its zaak in Mijn zaken.",
)
@pytest.mark.scenario("""
    Given a zaak in Open Zaak of a company's vestiging
    When the company logs in to Open Inwoner with eHerkenning
    Then Mijn zaken lists the zaak
""")
def test_bedrijfs_zaak_is_in_mijn_zaken(
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
) -> None:
    """A zaak of the company's vestiging is listed after an eHerkenning login (TA int-141)."""
    need_bootstrap(BEDRIJF.name, *WIRING)
    zaak = zaak_of(openzaak, registry, parts, "bedrijf")
    log_in(page, podiumd_env, "bedrijf")
    expect_listed(page, zaak)


@pytest.mark.tc("OI-016", "OI-070")
@pytest.mark.parametrize("who", ["inwoner", "bedrijf"])
@pytest.mark.source("draaiboek OI-016, OI-070", "Information a gemachtigde is entitled to see is visible.")
@pytest.mark.scenario("""
    Given a zaak in Open Zaak of another inwoner
    And the inwoner or company is its gemachtigde
    When the gemachtigde logs in to Open Inwoner with DigiD or eHerkenning
    Then Mijn zaken lists the zaak
""")
def test_gemachtigde_sees_the_zaak_in_mijn_zaken(
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
    who: str,
) -> None:
    """Mijn zaken lists a zaak where the logged-in identity is belanghebbende, gemachtigde of the initiator.

    Open Inwoner 2.5.0 has no DigiD Machtigen login; it lists every zaak with a rol of the logged-in identity.
    Open Zaak allows one initiator per zaak.
    """
    need_bootstrap(LOGINS[who][0].name, *WIRING)
    zaak = zaak_of(openzaak, registry, parts, who, "belanghebbende", "gemachtigde")
    initiator = parts.roltypen["initiator"]
    make_rol(openzaak, registry, zaak, initiator, "natuurlijk_persoon", "machtiginggever", inpBsn=random_bsn())
    log_in(page, podiumd_env, who)
    expect_listed(page, zaak)


@pytest.mark.tc("OI-014", "OI-068")
@pytest.mark.parametrize("who", WHO)
@pytest.mark.source(
    "draaiboek OI-014, OI-068",
    "Every zaak shown in the portal has the correct status, exactly matching its status in ZAC.",
)
@pytest.mark.scenario("""
    Given a zaak in Open Zaak of an inwoner or company that got a second status
    When the inwoner or company opens the zaak in Mijn zaken
    Then the zaak shows its current status
""")
def test_zaak_shows_its_current_status(
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
    who: str,
) -> None:
    """The zaak's status page shows the status Open Zaak (and so ZAC) has now, not an earlier one."""
    need_bootstrap(LOGINS[who][0].name, *WIRING)
    zaak = zaak_of(openzaak, registry, parts, who)
    current = parts.statustypen[1]
    make_status(openzaak, zaak, str(current["url"]))
    open_zaak_status(page, podiumd_env, zaak, who)
    # The status page loads the zaak's data after the page itself, like the list.
    expect(page.locator("main")).to_contain_text(str(current["omschrijving"]), timeout=LIST_TIMEOUT_MS)


@pytest.mark.source(
    "TA regression/143-portaal-document-download.spec.ts",
    "An inwoner downloads a document of their own zaak, proving the download works end to end.",
)
@pytest.mark.source(
    "TA interaction/31-document-portaal-ui.spec.ts",
    "Documents of a zaak are visible to the logged-in inwoner on the zaak's detail page.",
)
@pytest.mark.scenario("""
    Given an inwoner's zaak in Open Zaak with a definitief document
    When the inwoner opens the zaak in Mijn zaken
    Then the zaak shows the document
    And the document downloads with its content
""")
def test_zaak_document_can_be_downloaded(
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
) -> None:
    """A definitief document of the zaak is on its status page and downloads with its content (TA int-31, reg-143)."""
    need_bootstrap(INWONER.name, *WIRING)
    zaak = zaak_of(openzaak, registry, parts)
    inhoud = registry.tagged("documentinhoud")
    document = make_document(openzaak, registry, parts.informatieobjecttype, inhoud, status="definitief")
    link_document(openzaak, registry, zaak, document)
    open_zaak_status(page, podiumd_env, zaak)
    # The status page loads the zaak's documents after the page itself ("Gegevens laden...").
    expect(page.get_by_text(str(document["titel"])).first).to_be_visible(timeout=LIST_TIMEOUT_MS)
    document_uuid = str(document["url"]).rsplit("/", 1)[-1]
    href = page.locator(f'a[href*="{document_uuid}"]').first.get_attribute("href")  # noqa: B907  # CSS selector
    assert href, "no download link for the document"
    download = browser_session(page, podiumd_env).get(
        re.sub(r"^/", f"{podiumd_env.profile.urls['openinwoner']}/", href)
    )
    assert inhoud in download.text


@pytest.mark.core
@pytest.mark.source(
    "TA interaction/162-portaal-document-upload-e2e.spec.ts",
    "An inwoner uploads a file in the portal and the document appears on the zaak in Open Zaak.",
)
@pytest.mark.source(
    "TA interaction/111-portaal-documenten-uploaden.spec.ts",
    "Documents can be uploaded from the portal's zaak detail page.",
)
@pytest.mark.scenario("""
    Given an inwoner's zaak in Open Zaak
    When the inwoner uploads a file on the zaak in Mijn zaken
    Then the file is a document of the zaak in Open Zaak
""")
def test_uploaded_document_reaches_the_zaak(
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
) -> None:
    """A file uploaded on the zaak's status page becomes a document of the zaak (TA int-111, int-162)."""
    need_bootstrap(INWONER.name, *WIRING, "openinwoner-zaaktype-config")
    zaak = zaak_of(openzaak, registry, parts)
    clean_up_new_documents(openzaak, registry, zaak)
    bestand = f"{registry.tagged('upload')}.txt"
    open_zaak_status(page, podiumd_env, zaak)
    upload_document(page, bestand, bestand.encode())
    found = wait_until(lambda: documents_of(openzaak, zaak), timeout=30, description=f"document {bestand} on the zaak")
    assert bestand in found


@pytest.mark.requires("cluster")
@pytest.mark.tc("OI-010", "OI-064")
@pytest.mark.parametrize("who", WHO)
@pytest.mark.source(
    "TA regression/123-portaal-clamav-eicar-rejectie.spec.ts",
    "The portal refuses harmful uploads through ClamAV's virus scan.",
)
@pytest.mark.usefixtures("virus_scan")
@pytest.mark.scenario("""
    Given Open Inwoner scans uploads for viruses
    And a zaak in Open Zaak of an inwoner or company
    When the inwoner or company uploads a test virus file on the zaak in Mijn zaken
    Then the zaak gets no document
""")
def test_infected_upload_is_refused(
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
    who: str,
) -> None:
    """With ClamAV on, an upload of the EICAR test file does not reach the zaak (TA reg-123)."""
    need_bootstrap(LOGINS[who][0].name, *WIRING, "openinwoner-zaaktype-config")
    zaak = zaak_of(openzaak, registry, parts, who)
    clean_up_new_documents(openzaak, registry, zaak)
    open_zaak_status(page, podiumd_env, zaak, who)
    upload_document(page, f"{registry.tagged('eicar')}.txt", EICAR)
    assert documents_of(openzaak, zaak) == []


@pytest.mark.tc("INT-018")
@pytest.mark.source(
    "TA regression/178-blacklist-upload.spec.ts",
    "Uploading a file with a blacklisted extension in the portal is refused with a message.",
)
@pytest.mark.scenario("""
    Given an inwoner's zaak in Open Zaak
    When the inwoner chooses an .html file to upload on the zaak in Mijn zaken
    Then the upload button stays disabled
""")
def test_refused_file_type_cannot_be_uploaded(
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
) -> None:
    """The upload form keeps its button disabled for a file type outside the allowed list, such as .html (TA reg-178)."""
    need_bootstrap(INWONER.name, *WIRING, "openinwoner-zaaktype-config")
    zaak = zaak_of(openzaak, registry, parts)
    open_zaak_status(page, podiumd_env, zaak)
    expect(choose_document(page, f"{registry.tagged('pagina')}.html", b"<html></html>")).to_be_disabled()


def expect_listed(page: Page, zaak: JsonObject) -> None:
    """Mijn zaken lists the zaak; it fetches the list from Open Zaak after the page loads, slower with much data."""
    expect(page.get_by_text(str(zaak["identificatie"])).first).to_be_visible(timeout=LIST_TIMEOUT_MS)


def open_zaak_status(page: Page, podiumd_env: Environment, zaak: JsonObject, who: str = "inwoner") -> None:
    """Log the identity in and open the zaak's status page from Mijn zaken."""
    log_in(page, podiumd_env, who)
    page.locator(f'a[href*="{zaak["uuid"]}"]').first.click()  # noqa: B907  # CSS selector


def documents_of(openzaak: ApiClient, zaak: JsonObject) -> list[str]:
    """The file names of the zaak's documents."""
    links = openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": str(zaak["url"])})
    return [str(openzaak.get(str(link["informatieobject"])).get("bestandsnaam")) for link in links]


@pytest.mark.core
@pytest.mark.source(
    "TA interaction/164-portaal-vraag-stellen-vanuit-zaak.spec.ts",
    "A question asked from the zaak detail page lands in Open Klant as a contactmoment linked to the zaak.",
)
@pytest.mark.scenario("""
    Given an inwoner's zaak in Open Zaak
    When the inwoner asks a question on the zaak in Mijn zaken
    Then Open Klant has one klantcontact about the zaak
    And it holds the question and the zaaknummer
""")
def test_question_about_a_zaak_reaches_open_klant(
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
    zaak = zaak_of(openzaak, registry, parts)
    about = {"onderwerpobjectidentificatorObjectId": str(zaak["uuid"])}

    def klantcontacten() -> list[str]:
        return [str(section(o, "klantcontact")["url"]) for o in openklant.list("onderwerpobjecten", about)]

    registry.add(
        f"questions about zaak {zaak['uuid']}",
        lambda: [delete_klantcontact_tree(openklant, k) for k in klantcontacten()],
    )
    vraag = registry.tagged("zaakvraag")
    open_zaak_status(page, podiumd_env, zaak)
    # htmx loads the form after the page (status/content/); typing before that settles leaves the button disabled.
    question = page.locator('#contact-form textarea[name="question"]')
    question.wait_for()
    page.wait_for_load_state("networkidle")
    question.fill(vraag)
    submit = page.locator("#submit_contact")
    expect(submit).not_to_have_class(re.compile(r"button--disabled"))
    submit.click()
    found = wait_until(klantcontacten, timeout=30, description=f"klantcontact about zaak {zaak['uuid']}")
    # Open Inwoner appends "Case number: <identificatie>" to the question.
    inhoud = [str(openklant.get(k).get("inhoud")) for k in found]
    assert len(inhoud) == 1
    assert inhoud[0].startswith(vraag)
    assert str(zaak["identificatie"]) in inhoud[0]


@pytest.mark.tc("ZAC-066")
@pytest.mark.requires("zac", "pabc")
@pytest.mark.source("draaiboek ZAC-066", "The portal shows zaken from ZAC correctly.")
@pytest.mark.scenario("""
    Given a behandelaar starts a zaak of an extern zaaktype in ZAC
    And completes its intake
    And makes the inwoner its initiator
    When the inwoner logs in to Open Inwoner with DigiD
    Then Mijn zaken lists the zaak
""")
def test_zaak_started_in_zac_shows_in_mijn_zaken(
    page: Page,
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_group: str,
    need_bootstrap: Callable[..., None],
) -> None:
    """A zaak started in ZAC with the inwoner as initiator is listed in the inwoner's Mijn zaken.

    The BPMN zaaktype is extern, which Open Inwoner requires; the intake gives the zaak a status.
    """
    need_bootstrap(INWONER.name, *WIRING)
    complete_intake(zac, urls["zac"], bpmn_zaak, (zac_group, ADMIN.username))
    make_person_initiator(zac, urls["zac"], bpmn_zaak, EREBOS)
    log_in(page, podiumd_env)
    expect_listed(page, bpmn_zaak)


@pytest.mark.requires("zac", "pabc", "mailpit")
@pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, documenten-mail):"
    " the stored mail PDF of E-mail versturen has the chosen vertrouwelijkheidaanduiding, openbaar ones show in"
    " the portal.",
)
@pytest.mark.scenario("""
    Given a zaak in ZAC of an extern zaaktype with the inwoner as initiator
    When the behandelaar sends two mails from the zaak and keeps them, one openbaar and one vertrouwelijk
    And the inwoner opens the zaak in Mijn zaken
    Then the zaak shows the openbaar mail
    And not the vertrouwelijk mail
""")
def test_only_openbaar_zac_mail_shows_in_the_portal(  # the zaak, its mails and the portal
    page: Page,
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_group: str,
    zac_mail: Callable[..., JsonObject],
    mailpit: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """Open Inwoner shows a zaak's documents up to its document_max_confidentiality, openbaar by default.

    The intake gives the BPMN zaak the status that Open Inwoner needs to list it.
    """
    need_bootstrap(INWONER.name, *WIRING)
    complete_intake(zac, urls["zac"], bpmn_zaak, (zac_group, ADMIN.username))
    make_person_initiator(zac, urls["zac"], bpmn_zaak, EREBOS)
    subjects = {}
    for vertrouwelijkheid in ("OPENBAAR", "VERTROUWELIJK"):
        body = zac_mail(
            bpmn_zaak,
            onderwerp=f"{vertrouwelijkheid} {{ZAAK_NUMMER}}",
            createDocumentFromMail=True,
            vertrouwelijkheidaanduiding=vertrouwelijkheid,
        )
        expect_status(send_mail(zac, urls["zac"], bpmn_zaak, body), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
        message = received_message(mailpit, registry, timeout=MAIL_TIMEOUT, to=str(body["ontvanger"]))
        subjects[vertrouwelijkheid] = str(message.get("Subject"))
    kept = {document.get("titel") for document in zaak_documents(zac, urls["zac"], bpmn_zaak)}
    assert set(subjects.values()) <= kept, kept
    open_zaak_status(page, podiumd_env, bpmn_zaak)
    expect(page.get_by_text(subjects["OPENBAAR"]).first).to_be_visible(timeout=LIST_TIMEOUT_MS)
    expect(page.get_by_text(subjects["VERTROUWELIJK"])).to_have_count(0)
