"""Chain: an Open Formulieren submission becomes a zaak in Open Zaak, and its PDF report downloads.

Ported from TA interaction 32 and 76, and regression 152.
"""

from __future__ import annotations

import re

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
from podiumd_tests.openformulieren import file_value
from podiumd_tests.openformulieren import forget_submission
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import registered_zaak
from podiumd_tests.openformulieren import save_step
from podiumd_tests.openformulieren import start_submission
from podiumd_tests.openformulieren import submission_action
from podiumd_tests.openformulieren import submission_summary
from podiumd_tests.openformulieren import submit
from podiumd_tests.openformulieren import upload_file
from podiumd_tests.pdf import verapdf_report
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


def _anonymous_submission(
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> tuple[requests.Session, JsonObject, JsonObject]:
    """Submit the test form without a login; the inwoner's session, the submission's status and its zaak."""
    need_bootstrap("openformulieren-form", "openformulieren-zgw-group", "openzaak-of-autorisatie")
    session = podiumd_env.session()
    data = {"klacht_omschrijving": registry.tagged("klacht"), **NAW_DATA}
    status = submit(podiumd_env, session, registry, TEST_FORM, data, timeout=REGISTRATION_TIMEOUT)
    return session, status, registered_zaak(podiumd_env, openzaak, registry, status)


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
    session, status, zaak = _anonymous_submission(podiumd_env, openzaak, registry, need_bootstrap)
    assert zaak["zaaktype"] == test_zaaktype["url"]
    assert openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": str(zaak["url"])})
    rollen = openzaak.list(f"{ZAKEN}/rollen", {"zaak": str(zaak["url"])})
    assert [section(r, "betrokkeneIdentificatie").get("geslachtsnaam") for r in rollen] == [NAW_DATA["achternaam"]]
    assert download_report(podiumd_env, session, status).startswith(b"%PDF")


@pytest.mark.source(
    "external ForumStandaardisatie/pdfchecker",
    "Government PDFs are checked for PDF/UA with veraPDF; Open Formulieren renders its report as PDF/UA-1.",
)
@pytest.mark.usefixtures("verapdf")
@pytest.mark.scenario("""
    Given an anonymous inwoner submitted the test form in Open Formulieren
    When the inwoner downloads the form as PDF
    Then veraPDF finds the PDF compliant with PDF/UA-1, which it claims
""")
def test_submission_report_passes_verapdf(
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """veraPDF finds the submission's PDF report compliant with the PDF/UA-1 it claims."""
    session, status, _ = _anonymous_submission(podiumd_env, openzaak, registry, need_bootstrap)
    assert verapdf_report(download_report(podiumd_env, session, status)) == {"ua1": []}


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


BIJLAGE = {
    "type": "file",
    "key": "bijlage",
    "label": "Bijlage",
    "fileMaxSize": "20KB",
    "storage": "url",
    "url": "",
    "multiple": False,
    "file": {"type": []},
}


@pytest.mark.requires("cluster")
@pytest.mark.source(
    "external GemeenteNijmegen/open-forms-testautomatisering helpers/file-upload.ts",
    "Uploads of 109 B, 13 kB, 555 kB and 1.5 MB: a form takes files up to its field's maximum size.",
)
@pytest.mark.parametrize(("size", "accepted"), [(109, True), (13_000, True), (555_000, False)])
@pytest.mark.scenario("""
    Given a form with a file field of at most 20 kB
    When an inwoner attaches a file of 109 B, 13 kB or 555 kB
    Then the step refuses the file above the maximum, naming the size
    And a submission with a smaller file becomes a zaak with that file as a document
""")
def test_file_field_takes_files_up_to_its_maximum(  # parametrized size
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
    size: int,
    accepted: bool,  # noqa: FBT001  # parameter
) -> None:
    """A file within fileMaxSize becomes a document of the zaak; above it Open Formulieren answers 413."""
    need_bootstrap("openformulieren-zgw-group", "openzaak-of-autorisatie")
    base = podiumd_env.profile.urls["openformulieren"]
    slug = registry.tagged(f"upload-{size}")
    make_form(podiumd_env, registry, slug, [*NAW, BIJLAGE], ZGW_REGISTRATION)
    http = podiumd_env.session()
    submission, headers = start_submission(http, base, slug)
    forget_submission(podiumd_env, registry, str(submission["id"]))
    upload = expect_status(upload_file(http, base, submission, headers, "bijlage.txt", b"x" * size), HTTPStatus.OK)
    data = {**NAW_DATA, "bijlage": [file_value(base, upload.json())]}
    if not accepted:
        response = expect_status(save_step(http, submission, headers, data), HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        assert re.search(r"maximale bestandsgrootte|maximum file size", response.text, re.IGNORECASE), response.text[
            :300
        ]
        return
    status = complete_submission(podiumd_env, http, submission, headers, data, timeout=REGISTRATION_TIMEOUT)
    zaak = registered_zaak(podiumd_env, openzaak, registry, status)
    links = openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": str(zaak["url"])})
    documents = [openzaak.get(str(link["informatieobject"])) for link in links]
    assert [d["bestandsomvang"] for d in documents if d["bestandsnaam"] == "bijlage.txt"] == [size]
