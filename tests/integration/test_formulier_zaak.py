"""Chain: an Open Formulieren submission becomes a zaak in Open Zaak. Ported from TA interaction 76."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_FORM
from podiumd_tests.openformulieren import delete_submission
from podiumd_tests.openformulieren import submit
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak

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
def test_submission_creates_a_zaak_with_the_form_pdf(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
    test_zaaktype: JsonObject,
) -> None:
    """A submitted form gives a zaak of the test zaaktype, with the submission's PDF as a document."""
    need_bootstrap("openformulieren-form")
    omschrijving = registry.tagged("klacht")
    status = submit(
        podiumd_env.session(),
        podiumd_env.profile.urls["openformulieren"],
        TEST_FORM,
        {"klacht_omschrijving": omschrijving},
        timeout=REGISTRATION_TIMEOUT,
    )
    submission = str(status["submission"])
    registry.add(f"submission {submission}", lambda: delete_submission(podiumd_env, submission))
    zaken = openzaak.list(f"{ZAKEN}/zaken", {"identificatie": str(status["publicReference"])})
    assert [z["zaaktype"] for z in zaken] == [test_zaaktype["url"]]
    zaak = str(zaken[0]["url"])
    registry.add(f"zaak {zaak}", lambda: delete_zaak(openzaak, zaak))
    assert openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": zaak})
