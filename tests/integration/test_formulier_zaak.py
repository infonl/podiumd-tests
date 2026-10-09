"""Chain: an Open Formulieren submission becomes a zaak in Open Zaak, and its PDF report downloads.

Ported from TA interaction 32 and 76, and regression 152.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_FORM
from podiumd_tests.bootstrap.steps import NAW_DATA
from podiumd_tests.bootstrap.steps import ZGW_REGISTRATION
from podiumd_tests.json_data import section
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import registered_zaak
from podiumd_tests.openformulieren import submit
from podiumd_tests.openformulieren import wait_for_registration
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import ZAKEN

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.integration, pytest.mark.requires("openformulieren", "openzaak")]

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
    report = expect_status(session.get(str(status["reportDownloadUrl"])), HTTPStatus.OK)
    assert report.content.startswith(b"%PDF")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Open Formulieren 3.5.5 registers an anonymous submission without name fields with an initiator rol"
    " without betrokkeneIdentificatie, which Open Zaak 1.29.3 refuses (400 invalid-betrokkene); the zaak and PDF"
    " exist, the registration fails; not yet reported upstream",
)
def test_anonymous_submission_without_a_name_registers(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    podiumd_env: Environment,
    http: requests.Session,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """A form without name fields, submitted without a login, registers a zaak."""
    need_bootstrap("openformulieren-zgw-group", "openzaak-of-autorisatie")
    slug = registry.tagged("anoniem")
    field = {"type": "textfield", "key": "omschrijving", "label": "Omschrijving"}
    make_form(podiumd_env, registry, slug, [field], ZGW_REGISTRATION)
    status = submit(
        podiumd_env, http, registry, slug, {"omschrijving": slug}, timeout=REGISTRATION_TIMEOUT, registers=False
    )
    registered_zaak(podiumd_env, openzaak, registry, status)
    wait_for_registration(podiumd_env, str(status["submission"]), timeout=REGISTRATION_TIMEOUT)
