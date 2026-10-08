"""Open Formulieren's public form API for the suite's test form (bootstrap openformulieren-form).

Ported from TA regression 75 and 79, and the cosign part of 153. The submission itself and its
zaak are the integration tests test_formulier_zaak and test_formulier_digid.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_FORM
from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.json_data import JsonObject

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
