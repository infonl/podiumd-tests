"""Chain: each Django app's mail reaches the environment's Mailpit. Merged from MK and PI test_mailpit.py."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

import pytest

from playwright.sync_api import expect

from podiumd_tests.components import DJANGO_APPS
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.json_data import section
from podiumd_tests.mailpit import delete_message
from podiumd_tests.mailpit import wait_for_mail
from podiumd_tests.pytest_plugin import requiring

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.integration, pytest.mark.requires("cluster", "mailpit")]

DELIVERY_TIMEOUT = 30


def send_and_receive(
    podiumd_env: Environment, mailpit: ApiClient, registry: ResourceRegistry, component: str
) -> tuple[JsonObject, dict[str, str]]:
    """Send a mail with the app's own settings; the message in Mailpit and what the app reported sending."""
    subject = registry.tagged(f"mail-{component}")
    sent = cast(
        "dict[str, str]",
        run_snippet(
            podiumd_env.kube,
            podiumd_env.deployment_for(component),
            "send_mail",
            {"subject": subject, "to": "ptest@example.invalid"},
        ),
    )
    message = wait_for_mail(mailpit, timeout=DELIVERY_TIMEOUT, subject=subject)
    registry.add(f"mail {subject}", lambda: delete_message(mailpit, str(message["ID"])))
    return message, sent


@pytest.mark.tc("INT-009")
@pytest.mark.parametrize("component", [requiring(c, c) for c in DJANGO_APPS])
def test_app_mail_reaches_mailpit(
    podiumd_env: Environment, mailpit: ApiClient, registry: ResourceRegistry, component: str
) -> None:
    """Mail sent with the app's own settings arrives in Mailpit from the app's DEFAULT_FROM_EMAIL."""
    message, sent = send_and_receive(podiumd_env, mailpit, registry, component)
    assert str(section(message, "From")["Address"]) in sent["from"]


@pytest.mark.ui
@pytest.mark.requires("openzaak")
def test_sent_mail_shows_in_the_mailpit_ui(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page, podiumd_env: Environment, mailpit: ApiClient, registry: ResourceRegistry, urls: dict[str, str]
) -> None:
    """Mailpit's web interface lists a mail an app sent, by its subject (MK test_mailpit.py)."""
    message, _ = send_and_receive(podiumd_env, mailpit, registry, "openzaak")
    page.goto(urls["mailpit"] + "/")
    expect(page.get_by_text(str(message["Subject"])).first).to_be_visible()
