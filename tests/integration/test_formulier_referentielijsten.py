"""Chain: a select field of Open Formulieren takes its options from a tabel in Referentielijsten.

The chosen item's code reaches the zaak as eigenschap kenteken of the test zaaktype.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import NAW
from podiumd_tests.bootstrap.steps import NAW_DATA
from podiumd_tests.bootstrap.steps import OF_REFERENTIELIJSTEN
from podiumd_tests.bootstrap.steps import ZGW_REGISTRATION
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.openformulieren import complete_submission
from podiumd_tests.openformulieren import forget_submission
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import referentielijsten_service
from podiumd_tests.openformulieren import registered_zaak
from podiumd_tests.openformulieren import save_step
from podiumd_tests.openformulieren import start_submission
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.referentielijsten import make_tabel

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires("openformulieren", "referentielijsten", "openzaak", "cluster"),
]

TIMEOUT = 90
ITEMS = [{"code": "rood", "naam": "Rood"}, {"code": "groen", "naam": "Groen"}]


@pytest.mark.source(
    "upstream open-formulieren/open-forms src/openforms/contrib/reference_lists/tests",
    "A select field lists the items of a Referentielijsten tabel and refuses a value that is not one of them.",
)
@pytest.mark.scenario("""
    Given a tabel in Referentielijsten with the items Rood and Groen
    And a form whose keuzelijst takes its options from that tabel
    When an inwoner opens the form
    Then the keuzelijst offers Rood and Groen
    And the form refuses to save a value that is not in the tabel
    When the inwoner chooses Groen and submits
    Then the new zaak has Groen's code as eigenschap
""")
def test_select_options_come_from_referentielijsten(
    podiumd_env: Environment,
    http: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """The keuzelijst offers the tabel's items, refuses another value and registers the chosen item's code."""
    need_bootstrap(OF_REFERENTIELIJSTEN.name, "openformulieren-zgw-group", "openzaak-of-autorisatie")
    tabel = registry.tagged("kleuren")
    make_tabel(podiumd_env, registry, tabel, ITEMS)

    keuzelijst = {
        "type": "select",
        "key": "kleur",
        "label": "Kleur",
        "data": {"values": []},
        "openForms": {"dataSrc": "referenceLists", "service": referentielijsten_service(podiumd_env), "code": tabel},
        "validate": {"required": True},
    }
    mapping = [{"component_key": "kleur", "eigenschap": "kenteken"}]
    registration = {
        **ZGW_REGISTRATION,
        "options": {**section(ZGW_REGISTRATION, "options"), "property_mappings": mapping},
    }
    slug = registry.tagged("referentielijst")
    make_form(podiumd_env, registry, slug, [keuzelijst, *NAW], registration)

    base = urls["openformulieren"]
    submission, headers = start_submission(http, base, slug)
    forget_submission(podiumd_env, registry, str(submission["id"]))
    step = expect_status(http.get(str(entries(submission["steps"])[0]["url"])), HTTPStatus.OK).json()
    configuration = section(step, "configuration")
    component = next(c for c in entries(configuration["components"]) if c["key"] == "kleur")
    assert sorted((v["value"], v["label"]) for v in entries(section(component, "data")["values"])) == sorted(
        (item["code"], item["naam"]) for item in ITEMS
    )

    refused = save_step(http, submission, headers, {"kleur": "paars", **NAW_DATA})
    assert refused.status_code == HTTPStatus.BAD_REQUEST, refused.text
    assert [(p["name"], p["code"]) for p in entries(refused.json()["invalidParams"])] == [
        ("data.kleur", "invalid_choice")
    ]

    status = complete_submission(
        podiumd_env, http, submission, headers, {"kleur": "groen", **NAW_DATA}, timeout=TIMEOUT
    )
    zaak = registered_zaak(podiumd_env, openzaak, registry, status)
    eigenschappen = openzaak.get(f"{zaak['url']}/zaakeigenschappen")
    assert [e.get("waarde") for e in entries(eigenschappen)] == ["groen"]
