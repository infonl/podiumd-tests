"""Chain: a logic rule a form designer saves blocks the step in Open Formulieren on one answer.

Pattern of Nijmegen's open-forms-testautomatisering (disable-next and blokkeert specs): logic rules are form
configuration that an upgrade can break, which the definition checks of the other tests do not see.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import OF_REDACTEUR
from podiumd_tests.bootstrap.steps import ZGW_REGISTRATION
from podiumd_tests.json_data import entries
from podiumd_tests.openformulieren import can_submit_step
from podiumd_tests.openformulieren import forget_submission
from podiumd_tests.openformulieren import form_and_headers
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import redacteur_session
from podiumd_tests.openformulieren import set_logic_rules
from podiumd_tests.openformulieren import start_submission

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires("openformulieren", "cluster"),
    pytest.mark.source(
        "external GemeenteNijmegen/open-forms-testautomatisering forms/*/*-disable-next.pw.ts",
        "A form's logic blocks Volgende on an answer that excludes the applicant.",
    ),
]

AKKOORD = {"type": "textfield", "key": "akkoord", "label": "Akkoord met de voorwaarden"}


@pytest.mark.scenario("""
    Given a form whose designer added a rule that blocks the step when the visitor answers "nee"
    When a visitor answers "nee"
    Then the form does not let the visitor go on
    And when the visitor answers "ja", it does
""")
def test_logic_rule_blocks_the_step_on_one_answer(
    http: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """A disable-next rule saved through the designer's API makes _check-logic refuse the step for "nee" only."""
    need_bootstrap(OF_REDACTEUR.name, "openformulieren-zgw-group")
    base = urls["openformulieren"]
    slug = registry.tagged("logica")
    make_form(podiumd_env, registry, slug, [AKKOORD], ZGW_REGISTRATION)
    form, _ = form_and_headers(redacteur_session(podiumd_env), base, slug)
    step_uuid = entries(form["steps"])[0]["uuid"]
    rule = {
        "form": form["url"],
        "description": registry.tagged("blokkeer"),
        "order": 0,
        "isAdvanced": False,
        "jsonLogicTrigger": {"==": [{"var": "akkoord"}, "nee"]},
        "actions": [{"formStepUuid": step_uuid, "action": {"type": "disable-next"}}],
    }
    set_logic_rules(redacteur_session(podiumd_env), base, form, [rule])
    submission, headers = start_submission(http, base, slug)
    forget_submission(podiumd_env, registry, str(submission["id"]))
    step = entries(submission["steps"])[0]
    assert not can_submit_step(http, step, headers, {"akkoord": "nee"})
    assert can_submit_step(http, step, headers, {"akkoord": "ja"})
