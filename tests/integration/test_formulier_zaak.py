"""Chain: an Open Formulieren submission becomes a zaak in Open Zaak, and its PDF report downloads.

Ported from TA interaction 32 and 76, and regression 152.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_FORM
from podiumd_tests.bootstrap.steps import NAW_DATA
from podiumd_tests.json_data import section
from podiumd_tests.openformulieren import download_report
from podiumd_tests.openformulieren import registered_zaak
from podiumd_tests.openformulieren import submit
from podiumd_tests.seed.openzaak import ZAKEN

if TYPE_CHECKING:
    from collections.abc import Callable

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
def test_submission_creates_a_zaak_with_the_form_pdf(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
    test_zaaktype: JsonObject,
) -> None:
    """An anonymous submission gives a zaak of the test zaaktype with the PDF and the filled-in name as initiator.

    The inwoner downloads the PDF.
    """
    need_bootstrap("openformulieren-form")
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
