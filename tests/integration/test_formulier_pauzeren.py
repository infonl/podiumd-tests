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
from podiumd_tests.openformulieren import save_step
from podiumd_tests.openformulieren import start_submission
from podiumd_tests.openformulieren import submission_action
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires("openformulieren", "mailpit", "cluster"),
    pytest.mark.source(
        "TA regression/154-omc-cosign-direct.spec.ts",
        "Checks that a created Open Formulieren submission has a resume URL, for completing it later.",
    ),
]

# Open Formulieren allows 3 pauses a minute per client address by default.
SUSPEND_TIMEOUT = 90


def resume_link(mail: str, submission: JsonObject) -> str:
    """Return the mail's link that names the submission."""
    links = [html.unescape(link) for link in re.findall(r'href="([^"]+)"', mail)]
    found = [link for link in links if str(submission["id"]) in link]
    assert found, f"no link to submission {submission['id']} in the mail"
    return found[0]


# Open Formulieren registers in a Celery task after _complete.
REGISTRATION_TIMEOUT = 90


@pytest.mark.tc("INT-009")
@pytest.mark.requires("openzaak")
@pytest.mark.source(
    "upstream open-formulieren/open-forms src/openforms/tests/e2e/test_resume_form.py",
    "Resuming a paused form through its resume URL shows the saved step, so the user can finish the form.",
)
@pytest.mark.scenario("""
    Given an inwoner has filled in a step of the test form in Open Formulieren
    When the inwoner pauses the form and gives an e-mail address
    Then that address receives a mail with a link to Open Formulieren
    When the inwoner opens the link in a new browser session
    Then the form shows the saved data
    And completing the form registers a zaak in Open Zaak
""")
def test_resume_link_continues_and_completes_the_submission(
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
    data = {"klacht_omschrijving": omschrijving}
    expect_status(save_step(http, submission, headers, data), HTTPStatus.CREATED, HTTPStatus.OK)
    address = f"{registry.tagged('hervat')}@example.invalid"
    suspend = submission_action(http, submission, "_suspend", {"email": address}, headers, timeout=SUSPEND_TIMEOUT)
    expect_status(suspend, HTTPStatus.CREATED)
    resume = resume_link(received(mailpit, registry, timeout=60, to=address), submission)
    assert url_host(resume) == url_host(base_url), f"resume link {resume} is not on Open Formulieren"
    resumed = podiumd_env.session()
    expect_status(resumed.get(resume), HTTPStatus.OK)
    _, resumed_headers = form_and_headers(resumed, base_url, TEST_FORM)
    again = expect_status(resumed.get(str(submission["url"])), HTTPStatus.OK).json()
    saved = expect_status(resumed.get(str(entries(again["steps"])[0]["url"])), HTTPStatus.OK).json()
    assert section(saved, "data").get("klacht_omschrijving") == omschrijving
    data = {**data, **NAW_DATA}
    status = complete_submission(podiumd_env, resumed, again, resumed_headers, data, timeout=REGISTRATION_TIMEOUT)
    assert registered_zaak(podiumd_env, openzaak, registry, status)["url"]
