"""Open Formulieren removes a registered submission's data once its form's removal limit has passed."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.mailpit import received
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import submit

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.integration, pytest.mark.requires("openformulieren", "mailpit", "cluster")]

TIMEOUT = 90
LIMIT_DAYS = 1


def kept_after_removal(podiumd_env: Environment, submission: str, age_days: int) -> bool:
    """Whether the submission survives the data removal task at this age (snippet openformulieren_data_removal)."""
    params: dict[str, object] = {"uuid": submission, "age_days": age_days}
    result = run_snippet(
        podiumd_env.kube, podiumd_env.deployment_for("openformulieren"), "openformulieren_data_removal", params
    )
    return bool(result["kept"])  # pyright: ignore[reportIndexIssue]


@pytest.mark.tc("OF-067")
def test_registered_submission_is_removed_after_the_limit(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    http: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """A registered submission stays within its form's removal limit and is deleted after it."""
    slug = registry.tagged("opschonen")
    address = f"{slug}@example.invalid"
    registration = {"backend": "email", "options": {"to_emails": [address]}}
    field = {"type": "textfield", "key": "omschrijving", "label": "Omschrijving"}
    make_form(
        podiumd_env,
        registry,
        slug,
        [field],
        registration,
        successful_submissions_removal_limit=LIMIT_DAYS,
        successful_submissions_removal_method="delete_permanently",
    )
    submission = str(submit(podiumd_env, http, registry, slug, {"omschrijving": slug}, timeout=TIMEOUT)["submission"])
    assert slug in received(mailpit, registry, timeout=TIMEOUT, to=address), "not registered"
    assert kept_after_removal(podiumd_env, submission, 0), "removed within the limit"
    assert not kept_after_removal(podiumd_env, submission, LIMIT_DAYS + 1), "kept after the limit"
