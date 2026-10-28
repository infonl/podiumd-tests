"""Chain: a paused Open Formulieren submission mails its resume link, through the environment's Mailpit, and resumes.

Ported from the Open Formulieren parts of TA regression 154: TA only checked that a submission
starts and that the form publishes cosign options (test_formulier_api covers both).
"""

from __future__ import annotations

import html
import re

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_FORM
from podiumd_tests.bootstrap.steps import NAW_DATA
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.mailpit import received
from podiumd_tests.openformulieren import complete_submission
from podiumd_tests.openformulieren import forget_submission
from podiumd_tests.openformulieren import form_and_headers
from podiumd_tests.openformulieren import registered_zaak
from podiumd_tests.openformulieren import start_submission
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires("openformulieren", "mailpit", "cluster"),
    pytest.mark.source(
        "TA regression/154-omc-cosign-direct.spec.ts",
        "Checks that a created Open Formulieren submission has a resume URL, for completing it later.",
    ),
]


@pytest.mark.tc("INT-009")
def test_paused_submission_mails_its_resume_link(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    http: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    mailpit: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """Pausing a half-filled form sends the given address a mail with a link back to Open Formulieren (TA reg-154)."""
    need_bootstrap("openformulieren-form")
    submission, headers = start_submission(http, urls["openformulieren"], TEST_FORM)
    forget_submission(podiumd_env, registry, str(submission["id"]))
    step = entries(submission["steps"])[0]
    data = {"data": {"klacht_omschrijving": registry.tagged("gepauzeerd")}}
    expect_status(http.put(str(step["url"]), json=data, headers=headers), HTTPStatus.CREATED, HTTPStatus.OK)
    address = f"{registry.tagged('pauze')}@example.invalid"
    suspend = http.post(f"{submission['url']}/_suspend", json={"email": address}, headers=headers)
    expect_status(suspend, HTTPStatus.CREATED)
    html = received(mailpit, registry, timeout=60, to=address)
    assert url_host(urls["openformulieren"]) in html, "no link to Open Formulieren in the mail"


# Open Formulieren registers in a Celery task after _complete.
REGISTRATION_TIMEOUT = 90


@pytest.mark.requires("openzaak")
@pytest.mark.source(
    "upstream open-formulieren/open-forms src/openforms/tests/e2e/test_resume_form.py",
    "Resuming a paused form through its resume URL shows the saved step, so the user can finish the form.",
)
def test_resume_link_continues_and_completes_the_submission(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    http: requests.Session,
    podiumd_env: Environment,
    mailpit: ApiClient,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """In a new session, the mailed link opens the paused submission with its saved data; finishing it registers a zaak."""
    need_bootstrap("openformulieren-form")
    base_url = podiumd_env.profile.urls["openformulieren"]
    submission, headers = start_submission(http, base_url, TEST_FORM)
    forget_submission(podiumd_env, registry, str(submission["id"]))
    omschrijving = registry.tagged("hervat")
    step = entries(submission["steps"])[0]
    expect_status(
        http.put(str(step["url"]), json={"data": {"klacht_omschrijving": omschrijving}}, headers=headers), 201, 200
    )
    address = f"{registry.tagged('hervat')}@example.invalid"
    expect_status(http.post(f"{submission['url']}/_suspend", json={"email": address}, headers=headers), 201)
    links = re.findall(r'href="([^"]+)"', received(mailpit, registry, timeout=60, to=address))
    resume = next(html.unescape(link) for link in links if str(submission["id"]) in link)
    resumed = podiumd_env.session()
    expect_status(resumed.get(resume), HTTPStatus.OK)
    _, resumed_headers = form_and_headers(resumed, base_url, TEST_FORM)
    again = expect_status(resumed.get(str(submission["url"])), HTTPStatus.OK).json()
    saved = expect_status(resumed.get(str(entries(again["steps"])[0]["url"])), HTTPStatus.OK).json()
    assert section(saved, "data").get("klacht_omschrijving") == omschrijving
    data = {"klacht_omschrijving": omschrijving, **NAW_DATA}
    status = complete_submission(podiumd_env, resumed, again, resumed_headers, data, timeout=REGISTRATION_TIMEOUT)
    assert registered_zaak(podiumd_env, openzaak, registry, status)["url"]
