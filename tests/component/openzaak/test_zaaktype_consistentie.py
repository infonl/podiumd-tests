"""Open Zaak refuses on a zaak the statustype, informatieobjecttype, eigenschap, roltype or resultaattype of another zaaktype."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import BPMN_ZAAKTYPE
from podiumd_tests.json_data import entries
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.openzaak import published_zaaktype
from podiumd_tests.seed.openzaak import zaaktype_parts

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    # The other zaaktype is the one of ZAC's BPMN process, in the same test catalogus.
    pytest.mark.requires("openzaak", "zac"),
    pytest.mark.source(
        "external OneGround/ZGW-APIs-postman-tests ZGW business rules zrc-016 to zrc-020",
        "A status, zaakinformatieobject, zaakeigenschap, rol or resultaat must use a type of the zaak's own zaaktype.",
    ),
]


@pytest.fixture(scope="module", name="other")
def fixture_other(openzaak: ApiClient, need_bootstrap: Callable[..., None]) -> ZaaktypeParts:
    """Return the types of a second published zaaktype in the test catalogus."""
    need_bootstrap("openzaak-zaaktype-bpmn")
    return zaaktype_parts(openzaak, published_zaaktype(openzaak, BPMN_ZAAKTYPE, "openzaak-zaaktype-bpmn"))


type Request = tuple[str, dict[str, object]]


@dataclass(frozen=True)
class Given:
    """A zaak of the test zaaktype and the types of the other zaaktype."""

    openzaak: ApiClient
    registry: ResourceRegistry
    zaak: JsonObject
    other: ZaaktypeParts


def _status(given: Given) -> Request:
    gezet = datetime.now(tz=UTC).isoformat()
    statustype = given.other.statustypen[0]["url"]
    return "statussen", {"zaak": given.zaak["url"], "statustype": statustype, "datumStatusGezet": gezet}


def _zaakinformatieobject(given: Given) -> Request:
    document = make_document(given.openzaak, given.registry, given.other.informatieobjecttype)
    return "zaakinformatieobjecten", {"zaak": given.zaak["url"], "informatieobject": document["url"]}


def _zaakeigenschap(given: Given) -> Request:
    eigenschap = next(iter(given.other.eigenschappen.values()))
    body = {"zaak": given.zaak["url"], "eigenschap": eigenschap, "waarde": "x"}
    return f"{given.zaak['url']}/zaakeigenschappen", body


def _rol(given: Given) -> Request:
    return "rollen", {
        "zaak": given.zaak["url"],
        "betrokkeneType": "natuurlijk_persoon",
        "roltype": given.other.roltypen["initiator"],
        "roltoelichting": given.registry.tagged("rol"),
        "betrokkeneIdentificatie": {"inpBsn": "999990019"},
    }


def _resultaat(given: Given) -> Request:
    if not given.other.resultaattypen:
        pytest.skip("the other zaaktype has no resultaattype: Open Zaak reached no Selectielijst API at bootstrap")
    return "resultaten", {"zaak": given.zaak["url"], "resultaattype": given.other.resultaattypen[0]}


@pytest.mark.parametrize(
    ("request_of", "code"),
    [
        pytest.param(_status, "zaaktype-mismatch", id="status"),
        pytest.param(
            _zaakinformatieobject, "missing-zaaktype-informatieobjecttype-relation", id="zaakinformatieobject"
        ),
        pytest.param(_zaakeigenschap, "zaaktype-mismatch", id="zaakeigenschap"),
        pytest.param(_rol, "zaaktype-mismatch", id="rol"),
        pytest.param(_resultaat, "zaaktype-mismatch", id="resultaat"),
    ],
)
@pytest.mark.scenario("""
    Given a zaak of the test zaaktype
    When a status, document link, eigenschap, rol or resultaat with a type of another zaaktype is added to it
    Then Open Zaak refuses it
    And the error says the type does not belong to the zaak's zaaktype
""")
def test_type_of_another_zaaktype_is_refused(
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    other: ZaaktypeParts,
    request_of: Callable[[Given], Request],
    code: str,
) -> None:
    """Adding to a zaak an object whose type belongs to another zaaktype answers 400 with a zaaktype error code."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    path, body = request_of(Given(openzaak, registry, zaak, other))
    url = path if path.startswith("http") else f"{ZAKEN}/{path}"
    response = openzaak.request("POST", url, HTTPStatus.BAD_REQUEST, json=body)
    params = entries(response.json()["invalidParams"])
    assert [p["code"] for p in params] == [code], params
