"""Open Zaak validation of a zaak: each invalid field is named in invalidParams, on create and on change.

Ported from TA regression 44 and the ZGW business rules zrc-001, zrc-010 to zrc-015; unlike TA, every body is
valid except for the field under test.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_CATALOGUS_RSIN
from podiumd_tests.responses import invalid_names
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak_at_cleanup
from podiumd_tests.seed.openzaak import make_concept_zaaktype
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.openzaak import today

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from _pytest.mark import ParameterSet

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("openzaak"),
    pytest.mark.source(
        "TA regression/44-validation-edge-cases.spec.ts",
        "Open Zaak rejects common invalid payloads: too long, wrong enum, unknown zaaktype, missing field, bad date, short RSIN.",
    ),
    pytest.mark.source(
        "external OneGround/ZGW-APIs-postman-tests ZGW business rules zrc-001, zrc-010 to zrc-015",
        "A zaak is refused on create and change when a reference does not resolve, is of the wrong kind or breaks a rule.",
    ),
]

NOWHERE = "http://openzaak.invalid/zaken/api/v1/zaken/00000000-0000-0000-0000-000000000000"
MISSING = object()


@dataclass(frozen=True)
class Given:
    """What a case's invalid value may refer to: the zaak under change is None on create."""

    openzaak: ApiClient
    registry: ResourceRegistry
    parts: ZaaktypeParts
    zaak: JsonObject | None


type Value = object | Callable[[Given], object]


@dataclass(frozen=True)
class Case:
    """Fields of a zaak, the name invalidParams gives, the methods it applies to, known defects.

    A valid case has no name: before holds the fields of the zaak it changes, stored what Open Zaak then holds.
    """

    id: str
    fields: dict[str, Value]
    name: str = ""
    methods: tuple[str, ...] = ("POST", "PUT", "PATCH")
    xfail: dict[str, str] = field(default_factory=dict)  # method -> reason
    before: dict[str, object] = field(default_factory=dict)
    stored: dict[str, object] = field(default_factory=dict)


def _concept_zaaktype(given: Given) -> str:
    catalogus = str(given.openzaak.get(given.parts.zaaktype)["catalogus"])
    return str(make_concept_zaaktype(given.openzaak, given.registry, catalogus)["url"])


def _statustype(given: Given) -> str:
    return str(given.parts.statustypen[0]["url"])


def _the_zaak_itself(given: Given) -> str:
    return str((given.zaak or {})["url"])


CASES = [
    Case("omschrijving-too-long", {"omschrijving": "x" * 200}, "omschrijving"),
    Case("unknown-vertrouwelijkheid", {"vertrouwelijkheidaanduiding": "ultra-geheim"}, "vertrouwelijkheidaanduiding"),
    Case(
        "unknown-zaaktype", {"zaaktype": NOWHERE.replace("zaken/api/v1/zaken", "catalogi/api/v1/zaaktypen")}, "zaaktype"
    ),
    Case(
        "zaaktype-is-a-statustype",
        {"zaaktype": _statustype},
        "zaaktype",
        xfail={
            "POST": "[open-zaak-5] Open Zaak 1.29.3 answers 500 (StatusType has no catalogus in has_auth) for a client "
            "with CatalogusAutorisaties; not yet reported upstream"
        },
    ),
    Case("concept-zaaktype", {"zaaktype": _concept_zaaktype}, "zaaktype"),
    Case("no-bronorganisatie", {"bronorganisatie": MISSING}, "bronorganisatie", ("POST", "PUT")),
    Case("short-rsin", {"bronorganisatie": "12345"}, "bronorganisatie"),
    Case("bad-date", {"startdatum": "tomorrow"}, "startdatum"),
    Case("unknown-communicatiekanaal", {"communicatiekanaal": NOWHERE}, "communicatiekanaal"),
    Case("communicatiekanaal-is-a-statustype", {"communicatiekanaal": _statustype}, "communicatiekanaal"),
    Case(
        "unknown-relevante-andere-zaak",
        {"relevanteAndereZaken": [{"url": NOWHERE, "aardRelatie": "vervolg"}]},
        "relevanteAndereZaken",
    ),
    Case("opschorting-without-reden", {"opschorting": {"indicatie": True}}, "opschorting"),
    Case("verlenging-without-duur", {"verlenging": {"reden": "podiumd-tests"}}, "verlenging"),
    Case("unknown-hoofdzaak", {"hoofdzaak": NOWHERE}, "hoofdzaak"),
    Case("hoofdzaak-is-a-statustype", {"hoofdzaak": _statustype}, "hoofdzaak"),
    Case("hoofdzaak-is-the-zaak-itself", {"hoofdzaak": _the_zaak_itself}, "hoofdzaak", ("PUT", "PATCH")),
    Case(
        "betaaldatum-without-betaling",
        {"betalingsindicatie": "nvt", "laatsteBetaaldatum": f"{today()}T12:00:00Z"},
        "laatsteBetaaldatum",
        ("POST",),
    ),
    Case(
        "product-not-of-the-zaaktype", {"productenOfDiensten": ["https://example.com/product/1"]}, "productenOfDiensten"
    ),
]
VALID_CASES = [
    Case("opschorting-null", {"opschorting": None}),
    Case("verlenging-null", {"verlenging": None}, stored={"verlenging": None}),
    Case(
        "betaling-nvt-clears-betaaldatum",
        {"betalingsindicatie": "nvt"},
        methods=("PUT", "PATCH"),
        before={"betalingsindicatie": "geheel", "laatsteBetaaldatum": "2026-01-01T12:00:00Z"},
        stored={"betalingsindicatie": "nvt", "laatsteBetaaldatum": None},
    ),
]


def _body(given: Given, case: Case) -> dict[str, object]:
    body: dict[str, object] = {
        "bronorganisatie": TEST_CATALOGUS_RSIN,
        "verantwoordelijkeOrganisatie": TEST_CATALOGUS_RSIN,
        "zaaktype": given.parts.zaaktype,
        "startdatum": today(),
        "omschrijving": given.registry.tagged("zaak"),
    }
    for key, value in case.fields.items():
        body[key] = value(given) if callable(value) else value
    return {key: value for key, value in body.items() if value is not MISSING}


def _params(cases: list[Case]) -> list[ParameterSet]:
    return [
        pytest.param(
            case,
            method,
            id=f"{case.id}-{method}",
            marks=[pytest.mark.xfail(strict=True, reason=case.xfail[method])] if method in case.xfail else [],
        )
        for case in cases
        for method in case.methods
    ]


def _send(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts, case: Case, method: str, status: int
) -> requests.Response:
    """Create a zaak with the case's fields, or replace or change a zaak with them; Open Zaak's answer."""
    zaak = None if method == "POST" else make_zaak(openzaak, registry, parts.zaaktype, **case.before)
    body = _body(Given(openzaak, registry, parts, zaak), case)
    if zaak is None:
        response = openzaak.request("POST", f"{ZAKEN}/zaken", status, json=body)
        if response.status_code == HTTPStatus.CREATED:
            delete_zaak_at_cleanup(openzaak, registry, str(response.json()["url"]))
        return response
    changed = body if method == "PUT" else {key: body[key] for key in case.fields if key in body}
    return openzaak.request(method, str(zaak["url"]), status, json=changed)


@pytest.mark.parametrize(("case", "method"), _params(CASES))
@pytest.mark.scenario("""
    Given a zaak with one invalid or missing field
    When it is created, replaced or changed in Open Zaak
    Then Open Zaak refuses the zaak as invalid
    And the error names that field
""")
def test_invalid_zaak_names_the_field(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts, case: Case, method: str
) -> None:
    """POST, PUT or PATCH of a zaak with one invalid field answers 400 and names that field."""
    names = invalid_names(_send(openzaak, registry, parts, case, method, HTTPStatus.BAD_REQUEST))
    assert any(name == case.name or name.startswith(f"{case.name}.") for name in names), names


@pytest.mark.parametrize(("case", "method"), _params(VALID_CASES))
@pytest.mark.scenario("""
    Given a zaak in Open Zaak
    When it is created, replaced or changed with no opschorting or no verlenging
    Then Open Zaak accepts it
    When its betalingsindicatie becomes "not applicable"
    Then the zaak no longer has a date of its last payment
""")
def test_valid_zaak_is_stored(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts, case: Case, method: str
) -> None:
    """POST, PUT or PATCH of a zaak with null opschorting or verlenging, or betalingsindicatie nvt, is stored."""
    status = HTTPStatus.CREATED if method == "POST" else HTTPStatus.OK
    stored = _send(openzaak, registry, parts, case, method, status).json()
    assert {key: stored[key] for key in case.stored} == case.stored
