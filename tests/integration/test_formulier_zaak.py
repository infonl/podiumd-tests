"""Chain: an Open Formulieren submission becomes a zaak in Open Zaak, and its PDF report downloads.

Ported from TA interaction 32 and 76, and regression 152.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_FORM
from podiumd_tests.openformulieren import registered_zaak
from podiumd_tests.openformulieren import submit
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import ZAKEN

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.integration, pytest.mark.requires("openformulieren", "openzaak")]

# Open Formulieren registers in a Celery task after _complete.
REGISTRATION_TIMEOUT = 90


@pytest.mark.core
@pytest.mark.tc("OF-020")
def test_submission_creates_a_zaak_with_the_form_pdf(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
    test_zaaktype: JsonObject,
) -> None:
    """A submitted form gives a zaak of the test zaaktype with the PDF as a document; the inwoner downloads it."""
    need_bootstrap("openformulieren-form")
    omschrijving = registry.tagged("klacht")
    session = podiumd_env.session()
    status = submit(
        session,
        podiumd_env.profile.urls["openformulieren"],
        TEST_FORM,
        {"klacht_omschrijving": omschrijving},
        timeout=REGISTRATION_TIMEOUT,
    )
    zaak = registered_zaak(podiumd_env, openzaak, registry, status)
    assert zaak["zaaktype"] == test_zaaktype["url"]
    assert openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": str(zaak["url"])})
    report = expect_status(session.get(str(status["reportDownloadUrl"])), HTTPStatus.OK)
    assert report.content.startswith(b"%PDF")
