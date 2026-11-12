"""Open Zaak closing and reopening a zaak: einddatum, documents' gebruiksrechten, closed zaak protection, heropenen."""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import invalid_codes
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import close_zaak
from podiumd_tests.seed.openzaak import link_document
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import make_gebruiksrechten
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.openzaak import status_body

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openzaak")]


@pytest.fixture(name="closable")
def fixture_closable(parts: ZaaktypeParts) -> ZaaktypeParts:
    """Return the test zaaktype's types, when it has the resultaattype closing needs."""
    if not parts.resultaattypen:
        pytest.skip("test zaaktype has no resultaattype (Selectielijst API was unreachable at bootstrap)")
    return parts


def _closed(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> JsonObject:
    return close_zaak(openzaak, make_zaak(openzaak, registry, parts.zaaktype), parts)


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule zrc-007a",
    "The eindstatus sets the zaak's einddatum to the date the status was set.",
)
@pytest.mark.scenario("""
    Given a zaak in Open Zaak
    When it gets a resultaat and an eindstatus set two days ago
    Then the zaak's einddatum is the date of two days ago
""")
def test_einddatum_is_the_date_of_the_eindstatus(
    openzaak: ApiClient, registry: ResourceRegistry, closable: ZaaktypeParts
) -> None:
    """The einddatum of a closed zaak is the date of its eindstatus's datumStatusGezet."""
    gezet = datetime.now(tz=UTC).replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=2)
    closed = close_zaak(openzaak, make_zaak(openzaak, registry, closable.zaaktype), closable, gezet)
    assert closed["einddatum"] == gezet.date().isoformat()


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rules zrc-007b, drc-006",
    "A zaak closes only when every document has indicatieGebruiksrecht; creating gebruiksrechten sets it.",
)
@pytest.mark.scenario("""
    Given a zaak with a document whose gebruiksrechten are not recorded
    When the zaak gets its eindstatus
    Then Open Zaak refuses to close the zaak
    And once gebruiksrechten are recorded for the document, the zaak closes
""")
def test_zaak_closes_only_with_gebruiksrechten_of_its_documents(
    openzaak: ApiClient, registry: ResourceRegistry, closable: ZaaktypeParts
) -> None:
    """The eindstatus is refused while a document's indicatieGebruiksrecht is null, and accepted once it is set."""
    zaak = make_zaak(openzaak, registry, closable.zaaktype)
    # make_document records indicatieGebruiksrecht false, which allows closing.
    document = make_document(openzaak, registry, closable.informatieobjecttype, indicatieGebruiksrecht=None)
    link_document(openzaak, registry, zaak, document)
    openzaak.post(f"{ZAKEN}/resultaten", {"zaak": zaak["url"], "resultaattype": closable.resultaattypen[0]})
    eindstatus = status_body(zaak, str(closable.statustypen[-1]["url"]), "Afgehandeld")
    response = openzaak.request("POST", f"{ZAKEN}/statussen", HTTPStatus.BAD_REQUEST, json=eindstatus)
    assert invalid_codes(response) == ["indicatiegebruiksrecht-unset"], response.text
    make_gebruiksrechten(openzaak, registry, document)
    assert openzaak.get(str(document["url"]))["indicatieGebruiksrecht"] is True
    openzaak.post(f"{ZAKEN}/statussen", eindstatus)
    assert openzaak.get(str(zaak["url"]))["einddatum"]


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule zrc-007c to zrc-007p",
    "A closed zaak and what belongs to it change only for a client with zaken.geforceerd-bijwerken.",
)
@pytest.mark.parametrize("change", ["patch-zaak", "add-rol", "add-status"])
@pytest.mark.scenario("""
    Given a closed zaak in Open Zaak
    When a client without the right to change closed zaken changes the zaak or adds to it
    Then Open Zaak refuses it
    And a client with that right may make the same change
""")
def test_closed_zaak_changes_only_with_geforceerd_bijwerken(
    openzaak: ApiClient,
    openzaak_gesloten: ApiClient,
    registry: ResourceRegistry,
    closable: ZaaktypeParts,
    change: str,
) -> None:
    """A change to a closed zaak is refused without zaken.geforceerd-bijwerken and accepted with it."""
    zaak = _closed(openzaak, registry, closable)
    method, path, body = {
        "patch-zaak": ("PATCH", str(zaak["url"]), {"toelichting": registry.tagged("gesloten")}),
        "add-rol": (
            "POST",
            f"{ZAKEN}/rollen",
            {
                "zaak": zaak["url"],
                "betrokkeneType": "natuurlijk_persoon",
                "roltype": closable.roltypen["initiator"],
                "roltoelichting": registry.tagged("rol"),
                "betrokkeneIdentificatie": {"inpBsn": "999990019"},
            },
        ),
        "add-status": ("POST", f"{ZAKEN}/statussen", status_body(zaak, str(closable.statustypen[-1]["url"]))),
    }[change]
    openzaak_gesloten.request(method, path, *REFUSED, json=body)
    openzaak.request(method, path, HTTPStatus.OK, HTTPStatus.CREATED, json=body)


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule zrc-008",
    "A status that is not the eindstatus reopens a closed zaak, only for a client with zaken.heropenen.",
)
@pytest.mark.scenario("""
    Given a closed zaak in Open Zaak
    When a client without the right to reopen zaken gives it its first status again
    Then Open Zaak refuses it
    When a client with that right does
    Then the zaak is open again, without einddatum, archiefnominatie and archiefactiedatum
""")
def test_first_status_reopens_a_closed_zaak_only_with_heropenen(
    openzaak: ApiClient, openzaak_gesloten: ApiClient, registry: ResourceRegistry, closable: ZaaktypeParts
) -> None:
    """A non-eindstatus on a closed zaak needs zaken.heropenen and clears einddatum and the archive fields."""
    zaak = _closed(openzaak, registry, closable)
    heropend = status_body(zaak, str(closable.statustypen[0]["url"]), "Heropend")
    openzaak_gesloten.request("POST", f"{ZAKEN}/statussen", *REFUSED, json=heropend)
    openzaak.post(f"{ZAKEN}/statussen", heropend)
    reopened = openzaak.get(str(zaak["url"]))
    assert (reopened["einddatum"], reopened["archiefnominatie"], reopened["archiefactiedatum"]) == (None, None, None)


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule zrc-022",
    "A zaak starts as nog_te_archiveren; another archiefstatus needs archiefnominatie and archiefactiedatum.",
)
@pytest.mark.scenario("""
    Given a new zaak in Open Zaak
    Then its archiefstatus is "nog te archiveren"
    And Open Zaak refuses to mark it archived while it has no archiefnominatie and archiefactiedatum
""")
def test_archiefstatus_needs_the_archive_fields(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """archiefstatus defaults to nog_te_archiveren; gearchiveerd without archiefnominatie and archiefactiedatum is a 400."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    assert zaak["archiefstatus"] == "nog_te_archiveren"
    body = {"archiefstatus": "gearchiveerd"}
    response = openzaak.request("PATCH", str(zaak["url"]), HTTPStatus.BAD_REQUEST, json=body)
    assert invalid_codes(response), response.text
