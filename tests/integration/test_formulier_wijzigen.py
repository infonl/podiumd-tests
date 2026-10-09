"""Chain: a form changed through Open Formulieren's API still registers zaken, with the changed values.

The form editor is the bootstrap user OF_REDACTEUR (group Redacteurs). The change adds a field and
maps it to the test zaaktype's eigenschap kenteken (a variable mapping).
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import NAW
from podiumd_tests.bootstrap.steps import NAW_DATA
from podiumd_tests.bootstrap.steps import OF_REDACTEUR
from podiumd_tests.bootstrap.steps import ZGW_REGISTRATION
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import redacteur_session
from podiumd_tests.openformulieren import registered_zaak
from podiumd_tests.openformulieren import submit
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.integration, pytest.mark.requires("openformulieren", "openzaak", "cluster")]

TIMEOUT = 90
OMSCHRIJVING = {"type": "textfield", "key": "omschrijving", "label": "Omschrijving"}
KENTEKEN = {"type": "textfield", "key": "kenteken", "label": "Kenteken"}


@pytest.mark.tc("OF-068", "OF-073")
def test_changed_form_registers_the_new_field(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    http: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """After the editor adds a field mapped to a zaak eigenschap, a new submission's zaak has that value."""
    need_bootstrap(OF_REDACTEUR.name, "openformulieren-zgw-group", "openzaak-of-autorisatie")
    base = urls["openformulieren"]
    slug = registry.tagged("wijzigen")
    make_form(podiumd_env, registry, slug, [OMSCHRIJVING, *NAW], ZGW_REGISTRATION)
    before = submit(podiumd_env, http, registry, slug, {"omschrijving": slug, **NAW_DATA}, timeout=TIMEOUT)
    registered_zaak(podiumd_env, openzaak, registry, before)

    editor = redacteur_session(podiumd_env)
    form = expect_status(editor.get(f"{base}/api/v2/forms/{slug}"), HTTPStatus.OK).json()
    step = expect_status(editor.get(str(entries(form["steps"])[0]["url"])), HTTPStatus.OK).json()
    definition = str(step["formDefinition"])
    configuration = {"display": "form", "components": [OMSCHRIJVING, *NAW, KENTEKEN]}
    expect_status(editor.patch(definition, json={"configuration": configuration}), HTTPStatus.OK)
    # As the form designer does: save the step too, which gives the new field its form variable.
    expect_status(editor.patch(str(step["url"]), json={"formDefinition": definition}), HTTPStatus.OK)
    backends = entries(expect_status(editor.get(str(form["url"])), HTTPStatus.OK).json()["registrationBackends"])
    mapping = [{"componentKey": "kenteken", "eigenschap": "kenteken"}]
    changed = [{**b, "options": {**section(b, "options"), "propertyMappings": mapping}} for b in backends]
    expect_status(editor.patch(str(form["url"]), json={"registrationBackends": changed}), HTTPStatus.OK)

    kenteken = "AB-123-C"
    after = submit(
        podiumd_env, http, registry, slug, {"omschrijving": slug, "kenteken": kenteken, **NAW_DATA}, timeout=TIMEOUT
    )
    zaak = registered_zaak(podiumd_env, openzaak, registry, after)
    eigenschappen = openzaak.get(f"{zaak['url']}/zaakeigenschappen")
    assert [e.get("waarde") for e in entries(eigenschappen)] == [kenteken]
