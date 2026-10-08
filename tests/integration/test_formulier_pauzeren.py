"""Chain: a paused Open Formulieren submission mails its resume link, through the environment's Mailpit.

Ported from the Open Formulieren parts of TA regression 154: TA only checked that a submission
starts and that the form publishes cosign options (test_formulier_api covers both).
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_FORM
from podiumd_tests.json_data import entries
from podiumd_tests.mailpit import delete_message
from podiumd_tests.mailpit import wait_for_mail
from podiumd_tests.openformulieren import delete_submission
from podiumd_tests.openformulieren import start_submission
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.integration, pytest.mark.requires("openformulieren", "mailpit", "cluster")]


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
    registry.add(f"submission {submission['id']}", lambda: delete_submission(podiumd_env, str(submission["id"])))
    step = entries(submission["steps"])[0]
    data = {"data": {"klacht_omschrijving": registry.tagged("gepauzeerd")}}
    expect_status(http.put(str(step["url"]), json=data, headers=headers), HTTPStatus.CREATED, HTTPStatus.OK)
    address = f"{registry.tagged('pauze')}@example.invalid"
    suspend = http.post(f"{submission['url']}/_suspend", json={"email": address}, headers=headers)
    expect_status(suspend, HTTPStatus.CREATED)
    message = wait_for_mail(mailpit, timeout=60, to=address)
    registry.add(f"mail to {address}", lambda: delete_message(mailpit, str(message["ID"])))
    html = str(mailpit.get(f"message/{message['ID']}").get("HTML"))
    assert url_host(urls["openformulieren"]) in html, "no link to Open Formulieren in the mail"
