"""Chain: an Open Formulieren submission becomes a zaak in Open Zaak, and its PDF report downloads.

Ported from TA interaction 32 and 76, and regression 152.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_FORM
from podiumd_tests.bootstrap.steps import NAW
from podiumd_tests.bootstrap.steps import NAW_DATA
from podiumd_tests.bootstrap.steps import ZGW_REGISTRATION
from podiumd_tests.json_data import section
from podiumd_tests.openformulieren import COMPLETE
from podiumd_tests.openformulieren import complete_submission
from podiumd_tests.openformulieren import download_report
from podiumd_tests.openformulieren import forget_submission
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import registered_zaak
from podiumd_tests.openformulieren import save_step
from podiumd_tests.openformulieren import start_submission
from podiumd_tests.openformulieren import submission_action
from podiumd_tests.openformulieren import submission_summary
from podiumd_tests.openformulieren import submit
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import ZAKEN

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Mapping

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires("openformulieren", "openzaak"),
    pytest.mark.source(
        "TA interaction/76-of-submission-end-to-end.spec.ts",
        "A form filled in by a citizen leads to a zaak in Open Zaak, end to end.",
    ),
    pytest.mark.source(
        "TA interaction/32-of-submission-ui.spec.ts",
        "Checks the form API, its zaaktype link, the ZGW registration backend and creating a submission.",
    ),
    pytest.mark.source(
        "TA regression/152-of-retention-en-pdf.spec.ts", "A PDF of the submitted form is available to the citizen."
    ),
]

# Open Formulieren registers in a Celery task after _complete.
REGISTRATION_TIMEOUT = 90


@pytest.mark.core
@pytest.mark.tc("OF-007", "OF-020")
@pytest.mark.scenario("""
    Given the test form in Open Formulieren
    When an anonymous inwoner submits it
    Then a zaak of the test zaaktype exists in Open Zaak with the form as document
    And the filled-in name is its initiator
    And the inwoner can download the form as PDF
""")
def test_submission_creates_a_zaak_with_the_form_pdf(
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
    test_zaaktype: JsonObject,
) -> None:
    """An anonymous submission gives a zaak of the test zaaktype with the PDF and the filled-in name as initiator.

    The inwoner downloads the PDF.
    """
    need_bootstrap("openformulieren-form", "openformulieren-zgw-group", "openzaak-of-autorisatie")
    omschrijving = registry.tagged("klacht")
    session = podiumd_env.session()
    status = submit(
        podiumd_env,
        session,
        registry,
        TEST_FORM,
        {"klacht_omschrijving": omschrijving, **NAW_DATA},
        timeout=REGISTRATION_TIMEOUT,
    )
    zaak = registered_zaak(podiumd_env, openzaak, registry, status)
    assert zaak["zaaktype"] == test_zaaktype["url"]
    assert openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": str(zaak["url"])})
    rollen = openzaak.list(f"{ZAKEN}/rollen", {"zaak": str(zaak["url"])})
    assert [section(r, "betrokkeneIdentificatie").get("geslachtsnaam") for r in rollen] == [NAW_DATA["achternaam"]]
    assert download_report(podiumd_env, session, status).startswith(b"%PDF")


# A repeating group (Form.io editgrid) of at most three rows, each with a required naam.
KINDEREN = {
    "type": "editgrid",
    "key": "kinderen",
    "label": "Kinderen",
    "groupLabel": "Kind",
    "validate": {"maxLength": 3},
    "components": [
        {"type": "textfield", "key": "naam", "label": "Naam", "validate": {"required": True}},
        {"type": "number", "key": "leeftijd", "label": "Leeftijd"},
    ],
}


@pytest.mark.source(
    "external GemeenteNijmegen/open-forms-testautomatisering helpers/repeating-group.ts", "Add, save and edit a row."
)
@pytest.mark.scenario("""
    Given a form with a repeating group of at most three children, each with a required name
    When the inwoner adds two children and saves the step
    And changes the second child and saves again
    Then the overview shows both children with the changed second one
    And a fourth child is refused, and a child without a name cannot be submitted
    And the submission with the two children becomes a zaak
""")
def test_repeating_group_rows_are_added_edited_and_submitted(
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
    test_zaaktype: JsonObject,
) -> None:
    """Open Formulieren saves, changes and checks the rows of a repeating group, and registers the submission."""
    need_bootstrap("openformulieren-zgw-group", "openzaak-of-autorisatie")
    slug = registry.tagged("herhalend")
    make_form(podiumd_env, registry, slug, [*NAW, KINDEREN], ZGW_REGISTRATION)
    http = podiumd_env.session()
    submission, headers = start_submission(http, podiumd_env.profile.urls["openformulieren"], slug)
    forget_submission(podiumd_env, registry, str(submission["id"]))

    def save(*rows: Mapping[str, object]) -> requests.Response:
        return save_step(http, submission, headers, {**NAW_DATA, "kinderen": list(rows)})

    expect_status(save({"naam": "Anna", "leeftijd": 4}, {"naam": "Bob", "leeftijd": 7}), HTTPStatus.CREATED)
    gewijzigd = ({"naam": "Anna", "leeftijd": 4}, {"naam": "Bram", "leeftijd": 8})
    expect_status(save(*gewijzigd), HTTPStatus.OK)
    rijen = [pair for pair in submission_summary(http, submission, headers) if pair[0] != "Kinderen"][2:]
    assert rijen == [
        ("Kind 1", None),
        ("Naam", "Anna"),
        ("Leeftijd", 4),
        ("Kind 2", None),
        ("Naam", "Bram"),
        ("Leeftijd", 8),
    ]
    expect_status(save(*gewijzigd, {"naam": "C"}, {"naam": "D"}), HTTPStatus.BAD_REQUEST)
    expect_status(save(*gewijzigd, {"leeftijd": 1}), HTTPStatus.OK)
    refused = submission_action(http, submission, "_complete", COMPLETE, headers, timeout=REGISTRATION_TIMEOUT)
    assert expect_status(refused, HTTPStatus.BAD_REQUEST).json()["invalidParams"][0]["name"] == (
        "steps.0.data.kinderen.2.naam"
    )

    data = {**NAW_DATA, "kinderen": list(gewijzigd)}
    status = complete_submission(podiumd_env, http, submission, headers, data, timeout=REGISTRATION_TIMEOUT)
    assert registered_zaak(podiumd_env, openzaak, registry, status)["zaaktype"] == test_zaaktype["url"]
