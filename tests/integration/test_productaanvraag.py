"""Chain: a productaanvraag in Objecten becomes a zaak through Open Notificaties and ZAC.

Merged from MK and PI test_productaanvraag_flow.py. It uses the environment's own wiring:
the Productaanvraag-Dimpact objecttype, the objecten kanaal and ZAC's zaakafhandelparameters
for profile settings productaanvraag_type and productaanvraag_zaaktype. Betrokkenen, documents
and the Inbox productaanvragen use the BPMN test zaaktype: an estate's zaaktype can have the BRP
and KvK koppelingen off, and the suite cannot add documents of its informatieobjecttypen.
"""

from __future__ import annotations

import json

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.basisregistraties import KIERKEGAARD
from podiumd_tests.basisregistraties import KVK_TEST_NUMMER
from podiumd_tests.bootstrap.bpmn import bpmn_link
from podiumd_tests.bootstrap.bpmn import uuid_of
from podiumd_tests.bootstrap.names import BPMN_PRODUCTAANVRAAGTYPE
from podiumd_tests.json_data import section
from podiumd_tests.mailpit import received
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import submit
from podiumd_tests.seed.objecten import created_notificatie
from podiumd_tests.seed.objecten import make_productaanvraag
from podiumd_tests.seed.openklant import make_submission_contact
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import zaaktype_parts
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import PRODUCTAANVRAAG_TIMEOUT
from podiumd_tests.zac import assignment
from podiumd_tests.zac import clean_up_inbox_entries
from podiumd_tests.zac import deliver_notificatie
from podiumd_tests.zac import inbox_productaanvragen
from podiumd_tests.zac import open_task
from podiumd_tests.zac import productaanvraag_zaak
from podiumd_tests.zac import productaanvraag_zaken
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import start_zaak
from podiumd_tests.zac import wait_in_werkvoorraad
from podiumd_tests.zac import zaak_body
from podiumd_tests.zac_documents import zaak_documents

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.core,
    pytest.mark.requires("cluster", "objecten", "opennotificaties", "zac", "openzaak"),
]


@pytest.mark.source(
    "MK test_productaanvraag_flow.py",
    "A form submission through the Objects API and Open Notificaties makes ZAC create a zaak, with no manual step.",
)
@pytest.mark.source(
    "PI test_productaanvraag_flow.py",
    "A productaanvraag object makes ZAC create a zaak through the environment's standard chart wiring.",
)
@pytest.mark.scenario("""
    Given ZAC handles productaanvragen of a zaaktype
    When a productaanvraag is added to Objecten
    Then ZAC starts a zaak in Open Zaak that names the productaanvraag's kenmerk
""")
def test_productaanvraag_becomes_a_zaak(
    objecten: ApiClient,
    openzaak_productaanvraag: ApiClient,
    registry: ResourceRegistry,
    productaanvraagtype: str,
    productaanvraag_objecttype: str,
) -> None:
    """ZAC starts a zaak for a new productaanvraag object and names its kenmerk in the toelichting."""
    kenmerk = registry.tagged("productaanvraag")
    make_productaanvraag(objecten, registry, productaanvraag_objecttype, productaanvraagtype, kenmerk)
    productaanvraag_zaak(openzaak_productaanvraag, registry, kenmerk)


@pytest.mark.tc("OF-002")
@pytest.mark.requires("openklant", "mailpit", "keycloak")
@pytest.mark.usefixtures("ontvangstbevestiging")
@pytest.mark.source(
    "draaiboek OF-002",
    "A form leads to a zaak in ZAC, which automatically sends a receipt confirmation with the zaaknummer.",
)
@pytest.mark.scenario("""
    Given a form's submitter left an e-mail address in Open Klant
    When the form's productaanvraag makes ZAC start a zaak
    Then the submitter receives a mail with the zaaknummer
""")
def test_zac_mails_the_initiator_an_ontvangstbevestiging(
    objecten: ApiClient,
    openzaak_productaanvraag: ApiClient,
    openklant: ApiClient,
    mailpit: ApiClient,
    registry: ResourceRegistry,
    productaanvraagtype: str,
    productaanvraag_objecttype: str,
) -> None:
    """ZAC mails the zaaknummer to the e-mail address the form's submitter left in Open Klant."""
    kenmerk = registry.tagged("bevestigd")
    adres = f"{kenmerk}@example.invalid"
    make_submission_contact(openklant, registry, kenmerk, adres)
    make_productaanvraag(objecten, registry, productaanvraag_objecttype, productaanvraagtype, kenmerk)
    zaak = productaanvraag_zaak(openzaak_productaanvraag, registry, kenmerk)
    assert str(zaak["identificatie"]) in received(mailpit, registry, timeout=PRODUCTAANVRAAG_TIMEOUT, to=adres)


@pytest.mark.tc("FB-008")
@pytest.mark.requires("openformulieren")
@pytest.mark.source("draaiboek FB-008", "A new form can be set up that links to ZAC.")
@pytest.mark.source("ZAC features/3-open-formulieren.feature", "A submitted form becomes a zaak in ZAC's werkvoorraad.")
@pytest.mark.scenario("""
    Given a new form in Open Formulieren that registers a productaanvraag in Objecten
    When an inwoner submits the form
    Then ZAC starts a zaak for it in Open Zaak
    And the zaak is in ZAC's werkvoorraad
""")
def test_new_form_becomes_a_zac_zaak(
    podiumd_env: Environment,
    http: requests.Session,
    zac: requests.Session,
    objecten: ApiClient,
    openzaak_productaanvraag: ApiClient,
    registry: ResourceRegistry,
    productaanvraagtype: str,
    productaanvraag_objecttype: str,
) -> None:
    """A new form registered as a productaanvraag in Objecten, as the gemeente sets it up, makes ZAC start a zaak."""
    slug = registry.tagged("zac-formulier")
    # Open Formulieren's productaanvraag template, as the environments configure it.
    content = (
        '{"bron": {"naam": "Open Formulieren", "kenmerk": "{{ submission.public_reference }}"},'
        f' "type": {json.dumps(productaanvraagtype)}, "aanvraaggegevens": {{% json_summary %}}, "taal": "nld"}}'
    )
    registration = {
        "backend": "objects_api",
        "objects_api": f"{podiumd_env.profile.urls['objecten']}/api/v2/",
        "options": {
            "version": 1,
            "objecttype": productaanvraag_objecttype.rstrip("/").rsplit("/", 1)[-1],
            "objecttype_version": 1,
            "content_json": content,
            "update_existing_object": False,
            "upload_submission_csv": False,
            "auth_attribute_path": [],
            "iot_submission_report": "",
            "iot_submission_csv": "",
            "iot_attachment": "",
        },
    }
    field = {"type": "textfield", "key": "omschrijving", "label": "Omschrijving", "showInSummary": True}
    make_form(podiumd_env, registry, slug, [field], registration)
    status = submit(podiumd_env, http, registry, slug, {"omschrijving": slug}, timeout=PRODUCTAANVRAAG_TIMEOUT)
    kenmerk = str(status["publicReference"])
    registry.add(
        f"productaanvraag {kenmerk}",
        lambda: [
            objecten.delete(str(o["url"]))
            for o in objecten.list("objects", {"data_attr": f"bron__kenmerk__exact__{kenmerk}"})
        ],
    )
    zaak = productaanvraag_zaak(openzaak_productaanvraag, registry, kenmerk)
    wait_in_werkvoorraad(zac, podiumd_env.profile.urls["zac"], zaak)


# ZAC's handling of a productaanvraag.
PRODUCTAANVRAAG_SOURCE = "upstream infonl/dimpact-zaakafhandelcomponent src/main/kotlin/nl/info/zac/productaanvraag"
# The roltoelichting of a rol ZAC takes from a productaanvraag.
OVERGENOMEN = "Overgenomen vanuit de product aanvraag"
# The first user task of podiumd-tests' BPMN process; ZAC starts the process after it handled the productaanvraag.
INTAKE = "Intake"


@pytest.fixture(name="bpmn_productaanvraagtype")
def fixture_bpmn_productaanvraagtype(need_bootstrap: Callable[..., None]) -> str:
    """Return the productaanvraagtype ZAC starts zaken of the BPMN test zaaktype for."""
    need_bootstrap("zac-bpmn-process", "zac-bpmn-productaanvraag")
    return BPMN_PRODUCTAANVRAAGTYPE


def handled_zaak(
    zac: requests.Session, zac_url: str, openzaak: ApiClient, registry: ResourceRegistry, kenmerk: str
) -> JsonObject:
    """Return the BPMN zaak ZAC starts for the productaanvraag, once ZAC has handled it (its process started)."""
    zaak = productaanvraag_zaak(openzaak, registry, kenmerk)
    open_task(zac, zac_url, str(zaak["uuid"]), INTAKE)
    return zaak


def productaanvraag_rollen(openzaak: ApiClient, zaak: JsonObject) -> set[tuple[str, str, str]]:
    """(omschrijvingGeneriek, betrokkeneType, BSN or KvK-nummer) of each rol ZAC took from the productaanvraag."""
    rollen = openzaak.list(f"{ZAKEN}/rollen", {"zaak": str(zaak["url"])})
    found: set[tuple[str, str, str]] = set()
    for rol in rollen:
        if rol.get("roltoelichting") == OVERGENOMEN:
            identificatie = section(rol, "betrokkeneIdentificatie")
            nummer = identificatie.get("inpBsn") or identificatie.get("kvkNummer")
            found.add((str(rol["omschrijvingGeneriek"]), str(rol["betrokkeneType"]), str(nummer)))
    return found


@pytest.mark.source(PRODUCTAANVRAAG_SOURCE, "ZAC adds the productaanvraag's betrokkenen as rollen of their roltype.")
@pytest.mark.scenario("""
    Given ZAC starts zaken of the BPMN test zaaktype, with BRP and KvK koppelingen, for a productaanvraagtype
    When a productaanvraag names two initiators, a person and a company as belanghebbende, and a behandelaar
    Then the zaak has the first initiator as its only initiator
    And the person and the company as belanghebbenden
    And no behandelaar from the productaanvraag
""")
def test_betrokkenen_of_a_productaanvraag_become_rollen(
    zac: requests.Session,
    urls: dict[str, str],
    objecten: ApiClient,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    productaanvraag_objecttype: str,
    bpmn_productaanvraagtype: str,
) -> None:
    """ZAC adds the first initiator and a BSN and KvK belanghebbende; not a second initiator or a behandelaar."""
    kenmerk = registry.tagged("betrokkenen")
    betrokkenen = [
        {"inpBsn": EREBOS, "rolOmschrijvingGeneriek": "initiator"},
        {"inpBsn": KIERKEGAARD, "rolOmschrijvingGeneriek": "initiator"},
        {"inpBsn": KIERKEGAARD, "rolOmschrijvingGeneriek": "belanghebbende"},
        {"kvkNummer": KVK_TEST_NUMMER, "roltypeOmschrijving": "Belanghebbende"},
        {"inpBsn": EREBOS, "rolOmschrijvingGeneriek": "behandelaar"},
    ]
    make_productaanvraag(
        objecten, registry, productaanvraag_objecttype, bpmn_productaanvraagtype, kenmerk, betrokkenen=betrokkenen
    )
    zaak = handled_zaak(zac, urls["zac"], openzaak, registry, kenmerk)
    assert productaanvraag_rollen(openzaak, zaak) == {
        ("initiator", "natuurlijk_persoon", EREBOS),
        ("belanghebbende", "natuurlijk_persoon", KIERKEGAARD),
        ("belanghebbende", "niet_natuurlijk_persoon", KVK_TEST_NUMMER),
    }


@pytest.mark.source(PRODUCTAANVRAAG_SOURCE, "ZAC takes the zaak's details, location and documents from the aanvraag.")
@pytest.mark.scenario("""
    Given ZAC starts zaken of the BPMN test zaaktype for a productaanvraagtype
    When a productaanvraag with omschrijving, toelichting, location, its PDF and a bijlage is added to Objecten
    Then ZAC starts a zaak with that omschrijving and location, and the toelichting after the kenmerk
    And the zaak came in through E-formulier and has the zaaktype's groep and default behandelaar
    And the PDF, the bijlage and the productaanvraag are each linked to the zaak once
""")
def test_productaanvraag_zaak_takes_the_details_and_documents(
    zac: requests.Session,
    urls: dict[str, str],
    objecten: ApiClient,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    productaanvraag_objecttype: str,
    bpmn_productaanvraagtype: str,
    bpmn_zaaktype: JsonObject,
) -> None:
    """The zaak has the aanvraag's omschrijving, toelichting, point and documents, kanaal E-formulier and the link's assignment."""
    kenmerk = registry.tagged("gegevens")
    informatieobjecttype = zaaktype_parts(openzaak, bpmn_zaaktype).informatieobjecttype
    pdf = make_document(openzaak, registry, informatieobjecttype, bestandsnaam="aanvraag.pdf")
    bijlage = make_document(openzaak, registry, informatieobjecttype, titel=registry.tagged("bijlage"))
    # Latitude first, as Open Formulieren's map component writes it; GeoJSON has longitude first.
    zaakgegevens = {
        "omschrijving": kenmerk,
        "toelichting": "toelichting van de aanvrager",
        "geometry": {"type": "Point", "coordinates": [52.36673, 4.89316]},
    }
    created = make_productaanvraag(
        objecten,
        registry,
        productaanvraag_objecttype,
        bpmn_productaanvraagtype,
        kenmerk,
        zaakgegevens=zaakgegevens,
        pdf=pdf["url"],
        bijlagen=[bijlage["url"]],
    )
    zaak = handled_zaak(zac, urls["zac"], openzaak, registry, kenmerk)
    assert (zaak["omschrijving"], zaak["communicatiekanaalNaam"]) == (kenmerk, "E-formulier")
    assert str(zaak["toelichting"]).endswith(f"{kenmerk!r}. toelichting van de aanvrager")
    assert section(zaak, "zaakgeometrie") == {"type": "Point", "coordinates": [4.89316, 52.36673]}
    link = bpmn_link(zac, urls["zac"], uuid_of(bpmn_zaaktype["url"]))
    assert link is not None
    assigned = assignment(read_zaak(zac, urls["zac"], str(zaak["uuid"])))
    assert assigned == (link["groepNaam"], link["defaultBehandelaarId"])
    documents = openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": str(zaak["url"])})
    assert sorted(str(found["informatieobject"]) for found in documents) == sorted(
        [str(pdf["url"]), str(bijlage["url"])]
    )
    zaakobjecten = openzaak.list(f"{ZAKEN}/zaakobjecten", {"zaak": str(zaak["url"])})
    assert [found["object"] for found in zaakobjecten] == [created["url"]]


@pytest.mark.requires("openklant")
@pytest.mark.source(PRODUCTAANVRAAG_SOURCE, "ZAC links the contactgegevens left for this aanvraag to the zaak.")
@pytest.mark.scenario("""
    Given a form's submitter left an e-mail address and a telefoonnummer for this aanvraag only
    When the form's productaanvraag, without betrokkenen, makes ZAC start a zaak
    Then the zaak shows them as its zaakspecifieke contactgegevens and has no initiator
    And the zaak has the groep and behandelaar of the zaaktype's zaakafhandelparameters
""")
def test_aanvraagspecifieke_contactgegevens_are_on_the_zaak(
    zac: requests.Session,
    urls: dict[str, str],
    objecten: ApiClient,
    openzaak_productaanvraag: ApiClient,
    openklant: ApiClient,
    registry: ResourceRegistry,
    productaanvraagtype: str,
    productaanvraag_objecttype: str,
    zac_parameters: JsonObject,
) -> None:
    """ZAC shows the aanvraag's own e-mail address and telefoonnummer on the zaak, which has no initiator."""
    kenmerk = registry.tagged("contact")
    adres, telefoon = f"{kenmerk}@example.invalid", "0612345678"
    make_submission_contact(openklant, registry, kenmerk, adres, telefoon)
    make_productaanvraag(objecten, registry, productaanvraag_objecttype, productaanvraagtype, kenmerk)
    uuid = str(productaanvraag_zaak(openzaak_productaanvraag, registry, kenmerk)["uuid"])

    # ZAC links the contactgegevens after it assigned the zaak and added the betrokkenen.
    def shown() -> JsonObject | None:
        found = read_zaak(zac, urls["zac"], uuid)
        return found if found.get("zaakSpecificContactDetails") else None

    zaak = wait_until(shown, timeout=PRODUCTAANVRAAG_TIMEOUT, description=f"contactgegevens on zaak {uuid}")
    assert section(zaak, "zaakSpecificContactDetails") == {"emailAddress": adres, "telephoneNumber": telefoon}
    assert zaak.get("initiatorIdentificatie") is None
    assert assignment(zaak) == (zac_parameters["defaultGroepId"], zac_parameters.get("defaultBehandelaarId"))


@pytest.mark.source(PRODUCTAANVRAAG_SOURCE, "ZAC keeps a productaanvraag of a type it does not handle in its inbox.")
@pytest.mark.scenario("""
    Given a productaanvraag with an initiator, its PDF and a bijlage, of a type no zaaktype in ZAC handles
    When it is added to Objecten
    Then ZAC lists it in its Inbox productaanvragen with the initiator, the PDF and one bijlage
    When the behandelaar starts a zaak from it
    Then the zaak has the PDF, the bijlage and the aanvraag's gegevens, and the inbox no longer lists it
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
    pdf = make_document(openzaak, registry, informatieobjecttype, bestandsnaam="aanvraag.pdf")
    bijlage = make_document(openzaak, registry, informatieobjecttype, titel=registry.tagged("bijlage"))
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
    entry = wait_until(
        lambda: next(iter(inbox_productaanvragen(zac, urls["zac"], kenmerk)), None),
        timeout=PRODUCTAANVRAAG_TIMEOUT,
        description=f"productaanvraag {kenmerk} in the Inbox productaanvragen",
    )
    assert (entry["initiatorID"], entry["aanvraagdocumentUUID"], entry["aantalBijlagen"]) == (
        EREBOS,
        uuid_of(pdf["url"]),
        1,
    )
    body = zaak_body(bpmn_parameters, omschrijving=registry.tagged("inbox-zaak"))
    zaak = start_zaak(zac, urls["zac"], {**body, "inboxProductaanvraag": entry})
    url = f"{urls['openzaak']}/{ZAKEN}/zaken/{zaak['uuid']}"
    registry.add(f"zaak {zaak['identificatie']}", lambda: delete_zaak(openzaak, url))
    documents = {str(document["uuid"]) for document in zaak_documents(zac, urls["zac"], zaak)}
    assert documents == {uuid_of(pdf["url"]), uuid_of(bijlage["url"])}
    assert section(read_zaak(zac, urls["zac"], str(zaak["uuid"])), "zaakdata").get("omschrijving") == kenmerk
    assert inbox_productaanvragen(zac, urls["zac"], kenmerk) == []


@pytest.mark.source(PRODUCTAANVRAAG_SOURCE, "ZAC handles a productaanvraag once, also when notified of it again.")
@pytest.mark.scenario("""
    Given ZAC starts zaken of the BPMN test zaaktype for a productaanvraagtype
    When a productaanvraag is added and ZAC is notified of it three more times at once
    Then ZAC starts one zaak for it
""")
def test_repeated_notifications_start_one_zaak(
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    objecten: ApiClient,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    productaanvraag_objecttype: str,
    bpmn_productaanvraagtype: str,
) -> None:
    """Notifications of one productaanvraag that reach ZAC at the same time start one zaak."""
    kenmerk = registry.tagged("eenmaal")
    created = make_productaanvraag(objecten, registry, productaanvraag_objecttype, bpmn_productaanvraagtype, kenmerk)
    statuses = deliver_notificatie(podiumd_env, created_notificatie(created), 3)
    assert statuses == [HTTPStatus.NO_CONTENT for _ in range(3)]
    handled_zaak(zac, urls["zac"], openzaak, registry, kenmerk)
    assert len(productaanvraag_zaken(openzaak, kenmerk)) == 1
