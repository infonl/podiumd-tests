"""Chain: each Django app's mail reaches the environment's Mailpit. Merged from MK and PI test_mailpit.py."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.components import DJANGO_APPS
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.json_data import section
from podiumd_tests.mailpit import delete_message
from podiumd_tests.mailpit import wait_for_mail
from podiumd_tests.pytest_plugin import requiring

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.integration, pytest.mark.requires("cluster", "mailpit")]

DELIVERY_TIMEOUT = 30


@pytest.mark.parametrize("component", [requiring(c, c) for c in DJANGO_APPS])
@pytest.mark.tc("INT-009")
def test_app_mail_reaches_mailpit(
    podiumd_env: Environment, mailpit: ApiClient, registry: ResourceRegistry, component: str
) -> None:
    """Mail sent with the app's own settings arrives in Mailpit from the app's DEFAULT_FROM_EMAIL."""
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
    assert str(section(message, "From")["Address"]) in sent["from"]
