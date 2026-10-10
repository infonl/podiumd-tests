"""Chain: Open Inwoner with Open Klant 2 as klantensysteem: questions, a profile e-mail address.

Ported from TA interaction 181 and 182 and regression 108, 109 and 179. Open Inwoner reaches Open
Klant with its own token (wiring W6); the contact flow sends questions to the KCC actor (W8).
"""

from __future__ import annotations

import itertools

from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.auth.keycloak_admin import user_email
from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.bootstrap.steps import ITA_GROEP
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kcc import ita_detail_text
from podiumd_tests.kcc import kcc_login
from podiumd_tests.mailpit import forget_mails
from podiumd_tests.openinwoner import ask_anonymously
from podiumd_tests.openinwoner import portal_login
from podiumd_tests.openinwoner import set_account
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.objecten import clean_up_logboek
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openklant import clean_up_klantcontacten
from podiumd_tests.seed.openklant import expanded
from podiumd_tests.seed.openklant import klantcontact_body
from podiumd_tests.seed.openklant import klantcontacten_about
from podiumd_tests.seed.openklant import make_actor
from podiumd_tests.seed.openklant import make_betrokkene
from podiumd_tests.seed.openklant import make_klantcontact
from podiumd_tests.seed.openklant import partijen_of
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Locator
    from playwright.sync_api import Page

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.ui,
    pytest.mark.core,
    pytest.mark.requires("openinwoner", "openklant", "keycloak"),
]

INWONER, _, BEDRIJF = IDENTITIES
SUBJECT = "Algemene vraag"
# Open Inwoner's logins (W1), pages (W5) and Open Klant with the contact flow (W6, W8).
PORTAL_WIRING = ("openinwoner-oidc-mock", "openinwoner-cms-pages", "openinwoner-openklant")
MIJN_VRAGEN = "/mijn-zaken/contactmomenten/"
# PodiumD 3.3.0 showed at most 25 questions.
MANY_QUESTIONS = 26


def clean_up_question(podiumd_env: Environment, openklant: ApiClient, registry: ResourceRegistry, vraag: str) -> None:
    """Delete, at cleanup, the question's klantcontacten and the copy Open Inwoner mails to the contact address."""
    clean_up_klantcontacten(openklant, registry, SUBJECT, vraag)
    forget_mails(podiumd_env, registry, f'"{vraag}"')


def question_in_open_klant(openklant: ApiClient, vraag: str) -> JsonObject:
    """The klantcontact Open Inwoner makes for the question, once it is there."""
    found = wait_until(
        lambda: klantcontacten_about(openklant, SUBJECT, vraag), timeout=30, description=f"klantcontact {vraag}"
    )
    return found[0]


def asked_by(openklant: ApiClient, vraag: str) -> set[str]:
    """URLs of the partijen the question's klantcontact names as betrokkenen."""
    betrokkenen = expanded(openklant, str(question_in_open_klant(openklant, vraag)["url"]), "hadBetrokkenen")
    return {str(section(b, "wasPartij").get("url")) for b in betrokkenen}


def ask_in_mijn_vragen(page: Page, podiumd_env: Environment, vraag: str) -> Locator:
    """Log the inwoner in, ask the question in Mijn vragen; its card in the reloaded list."""
    mijn_vragen = podiumd_env.profile.urls["openinwoner"] + MIJN_VRAGEN
    portal_login(page, podiumd_env, "digid", INWONER, MIJN_VRAGEN)
    page.locator('select[name="subject"]').select_option(label=SUBJECT)
    page.locator('textarea[name="question"]').fill(vraag)
    email = page.locator('form:has(textarea[name="question"]) input[name="email"]')
    if email.count():
        email.first.fill(user_email(INWONER.username))
    page.locator("#submit_question").click()
    expect(page.get_by_text("Vraag verstuurd", exact=False).or_(page.locator(".notification")).first).to_be_visible()
    # The list does not refresh after submitting.
    page.goto(mijn_vragen)
    card = page.locator(".card", has_text=vraag)
    expect(card).to_be_visible()
    return card


@pytest.mark.tc("OI-031")
def test_question_shows_in_mijn_vragen(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openklant: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """A question asked in Mijn vragen becomes a klantcontact in Open Klant and is listed, unanswered (TA int-182)."""
    need_bootstrap(INWONER.name, *PORTAL_WIRING)
    vraag = registry.tagged("vraag")
    clean_up_question(podiumd_env, openklant, registry, vraag)
    card = ask_in_mijn_vragen(page, podiumd_env, vraag)
    expect(card).to_contain_text("Onbeantwoord")
    bsn = INWONER.attributes["bsn"][0]
    assert asked_by(openklant, vraag) & set(partijen_of(openklant, bsn)), "the question is not the inwoner's"


@pytest.mark.tc("OI-023")
def test_profile_email_reaches_open_klant(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openklant: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """An e-mail address saved in the profile becomes a digitaal adres of the inwoner's partij (TA reg-179)."""
    need_bootstrap(INWONER.name, *PORTAL_WIRING)
    bsn = INWONER.attributes["bsn"][0]
    adres = f"{registry.tagged('profiel')}@example.invalid"
    # The partij may predate the test (an earlier login made it); its new adres goes anyway. The
    # account keeps the address and every later login sends it again: set it back first.
    registry.add(
        f"digitaal adres {adres}",
        lambda: [openklant.delete(str(a["url"])) for a in openklant.list("digitaleadressen", {"adres": adres})],
    )
    registry.add(f"e-mail of account {bsn}", lambda: set_account(podiumd_env, bsn, email=user_email(INWONER.username)))
    portal_login(page, podiumd_env, "digid", INWONER, "/mijn-profiel/edit/")
    page.locator('input[name="email_addresses-0-value"]').first.fill(adres)
    page.get_by_role("button", name="Sla wijzigingen op").first.click()
    page.wait_for_url(lambda url: "/mijn-profiel/edit/" not in url)
    adressen = [
        str(a.get("adres"))
        for partij in partijen_of(openklant, bsn)
        for a in openklant.list("digitaleadressen", {"verstrektDoorPartij__uuid": partij.rsplit("/", 1)[-1]})
    ]
    assert adres in adressen


def test_company_question_reaches_open_klant(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openklant: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """After an eHerkenning login, the contact form sends the question to Open Klant as the vestiging's (TA reg-108, reg-109)."""
    need_bootstrap(BEDRIJF.name, *PORTAL_WIRING)
    vestiging = BEDRIJF.attributes["vestigingsnummer"][0]
    vraag = registry.tagged("bedrijfsvraag")
    clean_up_question(podiumd_env, openklant, registry, vraag)
    portal_login(page, podiumd_env, "eherkenning", BEDRIJF, "/contactformulier/")
    form = page.locator("#contactmoment-form")
    form.locator('select[name="subject"]').select_option(label=SUBJECT)
    form.locator('textarea[name="question"]').fill(vraag)
    form.get_by_role("button", name="Verzenden").click()
    assert asked_by(openklant, vraag) & set(partijen_of(openklant, vestiging)), "the question is not the vestiging's"


@pytest.mark.tc("OI-038", "OI-079")
def test_anonymous_question_reaches_open_klant(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openklant: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """Without a login, the contact form sends the question to Open Klant with the name and e-mail address, no partij."""
    need_bootstrap("openinwoner-cms-pages", "openinwoner-openklant")
    vraag = registry.tagged("anonieme-vraag")
    adres = f"{vraag}@example.invalid"
    clean_up_question(podiumd_env, openklant, registry, vraag)
    ask_anonymously(page, podiumd_env, SUBJECT, vraag, adres)
    betrokkene = expanded(openklant, str(question_in_open_klant(openklant, vraag)["url"]), "hadBetrokkenen")[0]
    assert betrokkene["wasPartij"] is None, "an anonymous question is linked to a partij"
    assert betrokkene["volledigeNaam"] == "Anoniem Test"
    assert [openklant.get(str(a["url"]))["adres"] for a in entries(betrokkene["digitaleAdressen"])] == [adres]


@pytest.mark.tc("OI-040", "OI-081")
def test_mijn_vragen_shows_more_than_one_page_of_questions(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openklant: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """Mijn vragen lists every question of the inwoner, also beyond the 25th."""
    need_bootstrap(INWONER.name, *PORTAL_WIRING)
    mijn_vragen = podiumd_env.profile.urls["openinwoner"] + MIJN_VRAGEN
    portal_login(page, podiumd_env, "digid", INWONER, MIJN_VRAGEN)
    partijen = partijen_of(openklant, INWONER.attributes["bsn"][0])
    assert len(partijen) == 1, f"inwoner has {len(partijen)} partijen in Open Klant"
    partij = {"uuid": partijen[0].rsplit("/", 1)[-1]}
    tag = registry.tagged("veel-vragen")
    for number in range(MANY_QUESTIONS):
        question = make_klantcontact(
            openklant, registry, kanaal="contactformulier", onderwerp=SUBJECT, inhoud=f"{tag}-{number}"
        )
        make_betrokkene(openklant, registry, question, partij)
    # Mijn vragen shows 9 questions per page; a page number past the last answers 404.
    shown = 0
    for number in itertools.count(1):
        response = page.goto(f"{mijn_vragen}?page={number}")
        if response and response.status == HTTPStatus.NOT_FOUND:
            break
        shown += page.locator(".card", has_text=tag).count()
    assert shown == MANY_QUESTIONS


@pytest.mark.requires("ita", "objecten")
def test_question_answered_in_ita_shows_as_answered(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """The KCC user answers an inwoner's question in ITA; Mijn vragen shows it answered, with the answer (TA int-181)."""
    need_bootstrap(
        INWONER.name,
        KCC.name,
        "openklant-actor-kcc",
        "openinwoner-oidc-mock",
        "openinwoner-cms-pages",
        "openinwoner-openklant",
    )
    vraag = registry.tagged("ita-vraag")
    clean_up_question(podiumd_env, openklant, registry, vraag)
    ask_in_mijn_vragen(page, podiumd_env, vraag)
    question = question_in_open_klant(openklant, vraag)
    taak = expanded(openklant, str(question["url"]), "leiddeTotInterneTaken")[0]
    clean_up_logboek(objecten, registry, objecttype_url(podiumd_env, "Activiteitenlog"), str(taak["uuid"]))
    antwoord = registry.tagged("ita-antwoord")
    clean_up_klantcontacten(openklant, registry, antwoord)
    page.context.clear_cookies()
    ita = kcc_login(page, podiumd_env, "ita")
    # The answer goes on the question's kanaal: Mijn vragen shows answers of that kanaal only.
    antwoord_body = klantcontact_body(
        registry, kanaal=question["kanaal"], onderwerp=antwoord, inhoud=f"Antwoord {antwoord}"
    )
    body = {
        "interneTaakId": taak["uuid"],
        "aanleidinggevendKlantcontactUuid": question["uuid"],
        # ITA links the answer to this partij; Mijn vragen lists only klantcontacten of the inwoner's partij.
        "partijUuid": section(expanded(openklant, str(question["url"]), "hadBetrokkenen")[0], "wasPartij")["uuid"],
        # ITA numbers the klantcontact itself.
        "klantcontactRequest": {k: v for k, v in antwoord_body.items() if k != "nummer"},
    }
    response = ita.post(podiumd_env.profile.urls["ita"] + "/api/klantcontacten/add-klantcontact", json=body)
    expect_status(response, HTTPStatus.OK, HTTPStatus.CREATED, HTTPStatus.NO_CONTENT)
    # ITA has no call to close the taak; KCC closes it as it does in ITA's UI.
    openklant.patch(str(taak["url"]), {"status": "verwerkt"})
    page.context.clear_cookies()
    portal_login(page, podiumd_env, "digid", INWONER, MIJN_VRAGEN)
    card = page.locator(".card", has_text=vraag)
    expect(card).to_contain_text("Beantwoord")
    card.locator("a").first.click()
    expect(page.locator("main")).to_contain_text(f"Antwoord {antwoord}")


@pytest.mark.tc("ZAC-067")
@pytest.mark.requires("zac")
def test_question_from_the_portal_shows_in_zac(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openklant: ApiClient,
    zac: requests.Session,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """A question the inwoner asks in Mijn vragen is among the inwoner's contactmomenten in ZAC.

    ZAC shows a klantcontact's onderwerp as its text, and pages over partijen, not contactmomenten:
    the inwoner's one partij is page 0.
    """
    need_bootstrap(INWONER.name, *PORTAL_WIRING)
    vraag = registry.tagged("zac-vraag")
    clean_up_question(podiumd_env, openklant, registry, vraag)
    asked = datetime.now(tz=UTC)
    ask_in_mijn_vragen(page, podiumd_env, vraag)
    query = {"bsn": INWONER.attributes["bsn"][0], "page": 0}
    found = zac.put(podiumd_env.profile.urls["zac"] + "/rest/klanten/contactmomenten", json=query)
    contactmomenten = entries(expect_status(found, HTTPStatus.OK).json()["resultaten"])
    assert any(
        c.get("tekst") == SUBJECT and datetime.fromisoformat(str(c["registratiedatum"])) >= asked
        for c in contactmomenten
    ), f"no question asked after {asked:%H:%M:%S} among {contactmomenten}"


@pytest.mark.tc("ITA-030")
@pytest.mark.requires("ita", "objecten")
def test_question_from_the_portal_shows_in_full_in_ita(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """A question from Mijn vragen, routed to the KCC user's groep, shows in ITA with its text."""
    need_bootstrap(INWONER.name, KCC.name, "openklant-actor-kcc", "objecten-medewerker-kcc", *PORTAL_WIRING)
    vraag = registry.tagged("ita-detail")
    clean_up_question(podiumd_env, openklant, registry, vraag)
    ask_in_mijn_vragen(page, podiumd_env, vraag)
    taak = expanded(openklant, str(question_in_open_klant(openklant, vraag)["url"]), "leiddeTotInterneTaken")[0]
    clean_up_logboek(objecten, registry, objecttype_url(podiumd_env, "Activiteitenlog"), str(taak["uuid"]))
    groep = make_actor(openklant, registry, "organisatorische_eenheid", ITA_GROEP, "grp")
    openklant.patch(
        str(taak["url"]), {"toegewezenAanActoren": [*entries(taak["toegewezenAanActoren"]), {"uuid": groep["uuid"]}]}
    )
    page.context.clear_cookies()
    ita = kcc_login(page, podiumd_env, "ita")
    assert vraag in ita_detail_text(ita, podiumd_env.profile.urls["ita"], taak)
