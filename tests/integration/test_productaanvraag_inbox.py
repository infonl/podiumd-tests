"""Chain: a productaanvraag of a type no zaaktype in ZAC handles goes to ZAC's Inbox productaanvragen.

It uses the BPMN test zaaktype for the zaak started from the inbox and the documents.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.bootstrap.bpmn import uuid_of
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.seed.objecten import make_productaanvraag
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import zaaktype_parts
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import E_FORMULIER
from podiumd_tests.zac import NOTIFICATION_TIMEOUT
from podiumd_tests.zac import PRODUCTAANVRAAG_SOURCE
from podiumd_tests.zac import PRODUCTAANVRAAG_TIMEOUT
from podiumd_tests.zac import clean_up_inbox_entries
from podiumd_tests.zac import clean_up_zaak
from podiumd_tests.zac import inbox_productaanvraag
from podiumd_tests.zac import inbox_productaanvragen
from podiumd_tests.zac import inbox_productaanvragen_page
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import start_zaak
from podiumd_tests.zac import zaak_body
from podiumd_tests.zac_beheer import communicatiekanalen
from podiumd_tests.zac_documents import inbox_documenten
from podiumd_tests.zac_documents import zaak_documents

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.core,
    pytest.mark.requires("cluster", "objecten", "opennotificaties", "zac", "openzaak"),
]


@pytest.mark.source(PRODUCTAANVRAAG_SOURCE, "ZAC keeps a productaanvraag of a type it does not handle in its inbox.")
@pytest.mark.scenario("""
    Given a PDF and a bijlage in ZAC's Inbox documenten
    And a productaanvraag with an initiator, the PDF and the bijlage, of a type no zaaktype in ZAC handles
    When it is added to Objecten
    Then ZAC lists it in its Inbox productaanvragen with the initiator, the PDF and one bijlage
    And the Inbox documenten no longer list the PDF and the bijlage
    When the behandelaar starts a zaak from it, through E-formulier, which ZAC offers only for such a zaak
    Then the zaak came in through E-formulier and has the PDF, the bijlage and the aanvraag's gegevens
    And the inbox no longer lists the productaanvraag
""")
def test_unhandled_productaanvraag_becomes_a_zaak_from_the_inbox(
    zac: requests.Session,
    urls: dict[str, str],
    objecten: ApiClient,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    productaanvraag_objecttype: str,
    bpmn_zaaktype: JsonObject,
    bpmn_parameters: JsonObject,
) -> None:
    """ZAC's Inbox productaanvragen lists the aanvraag; a zaak started from it gets its documents and gegevens."""
    kenmerk = registry.tagged("inbox")
    clean_up_inbox_entries(zac, urls["zac"], registry, kenmerk)
    informatieobjecttype = zaaktype_parts(openzaak, bpmn_zaaktype).informatieobjecttype
    pdf = make_document(openzaak, registry, informatieobjecttype, bestandsnaam="aanvraag.pdf", titel=f"{kenmerk}-pdf")
    bijlage = make_document(openzaak, registry, informatieobjecttype, titel=f"{kenmerk}-bijlage")
    # Before the productaanvraag: ZAC removes them from the Inbox documenten only when they are there.
    wait_until(
        lambda: len(inbox_documenten(zac, urls["zac"], kenmerk)) == 2,  # the PDF and the bijlage
        timeout=NOTIFICATION_TIMEOUT,
        description=f"the PDF and bijlage of {kenmerk} in ZAC's Inbox documenten",
    )
    betrokkenen = [{"inpBsn": EREBOS, "rolOmschrijvingGeneriek": "initiator"}]
    make_productaanvraag(
        objecten,
        registry,
        productaanvraag_objecttype,
        kenmerk,
        kenmerk,
        betrokkenen=betrokkenen,
        pdf=pdf["url"],
        bijlagen=[bijlage["url"]],
    )
    entry = inbox_productaanvraag(zac, urls["zac"], kenmerk)
    assert (entry["initiatorID"], entry["aanvraagdocumentUUID"], entry["aantalBijlagen"]) == (
        EREBOS,
        uuid_of(pdf["url"]),
        1,
    )
    assert inbox_documenten(zac, urls["zac"], kenmerk) == []
    assert E_FORMULIER in communicatiekanalen(zac, urls["zac"], inbox=True)
    assert E_FORMULIER not in communicatiekanalen(zac, urls["zac"])
    body = zaak_body(bpmn_parameters, omschrijving=registry.tagged("inbox-zaak"), communicatiekanaal=E_FORMULIER)
    zaak = start_zaak(zac, urls["zac"], {**body, "inboxProductaanvraag": entry})
    clean_up_zaak(zac, urls["zac"], openzaak, registry, zaak, with_documents=False)
    documents = {str(document["uuid"]) for document in zaak_documents(zac, urls["zac"], zaak)}
    assert documents == {uuid_of(pdf["url"]), uuid_of(bijlage["url"])}
    shown = read_zaak(zac, urls["zac"], str(zaak["uuid"]))
    assert (shown["communicatiekanaal"], section(shown, "zaakdata").get("omschrijving")) == (E_FORMULIER, kenmerk)
    assert inbox_productaanvragen(zac, urls["zac"], kenmerk) == []


@pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, "
    "zoeken-werklijsten-dashboard).",
)
@pytest.mark.scenario("""
    Given two productaanvragen of a type no zaaktype in ZAC handles
    When the behandelaar pages through the Inbox productaanvragen of that type one per page
    Then each page shows one productaanvraag with its ontvangstdatum, and the total of two
""")
def test_inbox_productaanvragen_are_paged_with_their_ontvangstdatum(
    zac: requests.Session,
    urls: dict[str, str],
    objecten: ApiClient,
    registry: ResourceRegistry,
    productaanvraag_objecttype: str,
) -> None:
    """maxResults pages ZAC's Inbox productaanvragen; totaal counts all of them; each has an ontvangstdatum."""
    zac_url = urls["zac"]
    soort = registry.tagged("inbox-pagina")
    clean_up_inbox_entries(zac, zac_url, registry, soort)
    made = [
        make_productaanvraag(objecten, registry, productaanvraag_objecttype, soort, f"{soort}-{number}")
        for number in range(2)
    ]
    wait_until(
        lambda: inbox_productaanvragen_page(zac, zac_url, soort, 0, 2).get("totaal") == len(made),
        timeout=PRODUCTAANVRAAG_TIMEOUT,
        description=f"the productaanvragen {soort} in the Inbox productaanvragen",
    )
    pages = [inbox_productaanvragen_page(zac, zac_url, soort, page, 1) for page in (0, 1)]
    shown = [entries(page.get("resultaten")) for page in pages]
    assert [(page.get("totaal"), len(found)) for page, found in zip(pages, shown, strict=True)] == [(2, 1), (2, 1)]
    assert {found[0].get("productaanvraagObjectUUID") for found in shown} == {aanvraag["uuid"] for aanvraag in made}
    assert all(found[0].get("ontvangstdatum") for found in shown), shown


@pytest.mark.xfail(
    strict=True,
    reason="[zac-34] ZAC 5.9.1 drops a productaanvraag of an unhandled type whose betrokkenen have no initiator "
    "(NoSuchElementException in registreerInbox, logged as a warning); not yet reported upstream",
)
@pytest.mark.source(PRODUCTAANVRAAG_SOURCE, "ZAC keeps a productaanvraag of a type it does not handle in its inbox.")
@pytest.mark.scenario("""
    Given a productaanvraag of a type no zaaktype in ZAC handles
    And its only betrokkene is a belanghebbende, no initiator
    Then ZAC lists it in its Inbox productaanvragen without initiator
""")
def test_unhandled_productaanvraag_without_initiator_reaches_the_inbox(
    zac: requests.Session,
    urls: dict[str, str],
    objecten: ApiClient,
    registry: ResourceRegistry,
    productaanvraag_objecttype: str,
) -> None:
    """A productaanvraag whose betrokkenen hold no initiator gets an Inbox productaanvragen entry."""
    soort = registry.tagged("inbox-zonder-initiator")
    clean_up_inbox_entries(zac, urls["zac"], registry, soort)
    betrokkenen = [{"inpBsn": EREBOS, "rolOmschrijvingGeneriek": "belanghebbende"}]
    make_productaanvraag(objecten, registry, productaanvraag_objecttype, soort, soort, betrokkenen=betrokkenen)
    entry = inbox_productaanvraag(zac, urls["zac"], soort)
    assert entry.get("initiatorID") is None
