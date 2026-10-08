"""Open Formulieren's public form API for the suite's test form (bootstrap openformulieren-form).

Ported from TA regression 75, 79 and 178, and the cosign part of 153. The submission itself and its
zaak are the integration tests test_formulier_zaak and test_formulier_digid.
"""

from __future__ import annotations

import re

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_FORM
from podiumd_tests.json_data import entries
from podiumd_tests.openformulieren import delete_submission
from podiumd_tests.openformulieren import start_submission
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openformulieren")]


@pytest.fixture(name="form")
def fixture_form(http: requests.Session, urls: dict[str, str], need_bootstrap: Callable[..., None]) -> JsonObject:
    """The test form as the form's JavaScript SDK reads it, anonymously."""
    need_bootstrap("openformulieren-form")
    return expect_status(http.get(f"{urls['openformulieren']}/api/v2/forms/{TEST_FORM}"), HTTPStatus.OK).json()


@pytest.mark.core
def test_test_form_takes_submissions(http: requests.Session, form: JsonObject) -> None:
    """The form is active, out of maintenance and has its one step with the klacht field (TA reg-75)."""
    assert (form["active"], form["maintenanceMode"], form["submissionAllowed"]) == (True, False, "yes")
    steps = entries(form["steps"])
    assert len(steps) == 1
    step = expect_status(http.get(str(steps[0]["url"])), HTTPStatus.OK).json()
    keys = [c.get("key") for c in entries(step["configuration"]["components"])]
    assert "klacht_omschrijving" in keys


def test_login_options_fit_login_required(form: JsonObject) -> None:
    """A form that requires a login offers one; the test form offers DigiD without requiring it (TA reg-75)."""
    options = [str(o.get("identifier")) for o in entries(form["loginOptions"])]
    assert not form["loginRequired"] or options
    assert "digid_oidc" in options


def test_form_publishes_its_settings(form: JsonObject) -> None:
    """The SDK gets the settings it renders with: cosign, confirmation mail, asterisks, pausing (TA reg-79, reg-153)."""
    assert isinstance(form["cosignLoginOptions"], list)
    for flag in ("sendConfirmationEmail", "requiredFieldsWithAsterisk", "suspensionAllowed"):
        assert isinstance(form[flag], bool), flag
    assert isinstance(form["resumeLinkLifetime"], int)
    assert form["resumeLinkLifetime"] > 0


@pytest.mark.requires("cluster")
@pytest.mark.parametrize(
    ("name", "message"),
    [
        pytest.param("document.pdf", r"geen \.pdf|not a \.pdf|geen geldig|not a valid", id="text-named-pdf"),
        pytest.param(
            "zonderextensie", r"bestandstype kon niet bepaald|extensie|could not.*determine", id="no-extension"
        ),
    ],
)
@pytest.mark.tc("INT-017")
def test_upload_of_a_false_file_is_refused(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    http: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
    name: str,
    message: str,
) -> None:
    """A file whose content does not match its name, or that has no extension, is refused with a reason (TA reg-178)."""
    need_bootstrap("openformulieren-form")
    submission, headers = start_submission(http, urls["openformulieren"], TEST_FORM)
    registry.add(f"submission {submission['id']}", lambda: delete_submission(podiumd_env, str(submission["id"])))
    upload = {"file": (name, b"plain text, no PDF", "application/pdf")}
    response = http.post(f"{urls['openformulieren']}/api/v2/formio/fileupload", files=upload, headers=headers)
    expect_status(response, HTTPStatus.BAD_REQUEST)
    assert re.search(message, response.text, re.IGNORECASE), response.text[:300]
