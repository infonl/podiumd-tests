"""Chain: Open Formulieren mails a submission, as registration or as confirmation, through the environment's Mailpit."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.mailpit import received
from podiumd_tests.openformulieren import delete_submission
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import submit

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.integration, pytest.mark.requires("openformulieren", "mailpit", "cluster")]

# Open Formulieren registers and mails in Celery tasks after _complete.
TIMEOUT = 90
OMSCHRIJVING = {"type": "textfield", "key": "omschrijving", "label": "Omschrijving", "validate": {"required": True}}


@pytest.mark.tc("OF-009", "OF-041")
def test_email_registration_mails_the_submission(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    http: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """A form with the e-mail registration backend mails the filled-in values to the registration address."""
    slug = registry.tagged("email-registratie")
    address = f"{slug}@example.invalid"
    make_form(podiumd_env, registry, slug, [OMSCHRIJVING], {"backend": "email", "options": {"to_emails": [address]}})
    omschrijving = registry.tagged("geregistreerd")
    status = submit(http, urls["openformulieren"], slug, {"omschrijving": omschrijving}, timeout=TIMEOUT)
    registry.add(
        f"submission {status['submission']}", lambda: delete_submission(podiumd_env, str(status["submission"]))
    )
    assert omschrijving in received(mailpit, registry, timeout=TIMEOUT, to=address)


@pytest.mark.tc("OF-040")
def test_confirmation_mail_summarises_the_submission(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    http: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """The filler gets a confirmation mail with the values they filled in."""
    slug = registry.tagged("bevestiging")
    email = {"type": "email", "key": "email", "label": "E-mail", "confirmationRecipient": True}
    registration = {"backend": "email", "options": {"to_emails": [f"{slug}-registratie@example.invalid"]}}
    # The summary lists only components with showInEmail.
    shown = {**OMSCHRIJVING, "showInEmail": True}
    make_form(podiumd_env, registry, slug, [shown, email], registration, send_confirmation_email=True)
    omschrijving = registry.tagged("samengevat")
    filler = f"{slug}@example.invalid"
    status = submit(
        http, urls["openformulieren"], slug, {"omschrijving": omschrijving, "email": filler}, timeout=TIMEOUT
    )
    registry.add(
        f"submission {status['submission']}", lambda: delete_submission(podiumd_env, str(status["submission"]))
    )
    assert omschrijving in received(mailpit, registry, timeout=TIMEOUT, to=filler)
