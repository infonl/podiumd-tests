"""Open Zaak validation of a zaak: each invalid field is named in invalidParams, on create and on change.

Ported from TA regression 44 and the ZGW business rules zrc-001, zrc-010 to zrc-015; unlike TA, every body is
valid except for the field under test.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_CATALOGUS_RSIN
from podiumd_tests.responses import invalid_names
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import make_concept_zaaktype
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.openzaak import today

if TYPE_CHECKING:
    from collections.abc import Callable

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
    """Fields that make a zaak invalid, the name invalidParams gives, the methods it applies to, known defects."""

    id: str
    fields: dict[str, Value]
    name: str
    methods: tuple[str, ...] = ("POST", "PUT", "PATCH")
    xfail: dict[str, str] = field(default_factory=dict)  # method -> reason


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


@pytest.mark.parametrize(
    ("case", "method"),
    [
        pytest.param(
            case,
            method,
            id=f"{case.id}-{method}",
            marks=[pytest.mark.xfail(strict=True, reason=case.xfail[method])] if method in case.xfail else [],
        )
        for case in CASES
        for method in case.methods
    ],
)
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
    zaak = None if method == "POST" else make_zaak(openzaak, registry, parts.zaaktype)
    body = _body(Given(openzaak, registry, parts, zaak), case)
    if zaak is None:
        response = openzaak.request("POST", f"{ZAKEN}/zaken", 400, json=body)
    else:
        changed = body if method == "PUT" else {key: body[key] for key in case.fields if key in body}
        response = openzaak.request(method, str(zaak["url"]), 400, json=changed)
    names = invalid_names(response)
    assert any(name == case.name or name.startswith(f"{case.name}.") for name in names), names
