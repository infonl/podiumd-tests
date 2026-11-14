"""Chain: Open Formulieren prefills a form from an inwoner's object in Objecten and updates that object.

The form opens with the object's uuid as initial data reference; the object's bsn names its owner, whom
Open Formulieren compares with the DigiD login (Keycloak's mock).
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.bpmn import uuid_of
from podiumd_tests.bootstrap.names import OBJECTEN_STORE_KEY
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.openformulieren import complete_submission
from podiumd_tests.openformulieren import forget_submission
from podiumd_tests.openformulieren import log_in_as
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import new_submission
from podiumd_tests.openformulieren import objects_token
from podiumd_tests.openformulieren import start_submission
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.objecten import make_granted_objecttype
from podiumd_tests.seed.objecten import make_object
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openklant import random_bsn

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires("openformulieren", "objecten", "keycloak", "cluster"),
]

TIMEOUT = 90
NAAM = {"type": "textfield", "key": "naam", "label": "Naam"}
# The object's owner: its data's bsn, compared with the login's BSN.
OWNER = ["bsn"]
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["bsn", "naam"],
    "properties": {"bsn": {"type": "string"}, "naam": {"type": "string"}},
}


@pytest.mark.source(
    "upstream open-formulieren/open-forms src/openforms/registrations/contrib/objects_api/tests",
    "A form opened with an object's reference prefills from it and updates it; another person's object is refused.",
)
@pytest.mark.scenario("""
    Given two objects in Objecten, one of the inwoner and one of another person
    And a form that prefills from an object and updates it on submission
    When the inwoner logs in with DigiD and opens the form with the inwoner's own object
    Then the form shows the object's naam
    When the inwoner changes the naam and submits
    Then Objecten has the new naam in a new record of the same object, and no new object
    And the form refuses to open with the other person's object
""")
def test_form_prefills_and_updates_the_inwoners_object(
    podiumd_env: Environment,
    urls: dict[str, str],
    objecten: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """The inwoner's object prefills the form and gets the submitted naam; another's object is refused."""
    need_bootstrap("openformulieren-oidc-mock")
    objecten_api = f"{urls['objecten']}/api/v2/"
    tokens = [podiumd_env.credentials.get(OBJECTEN_STORE_KEY), objects_token(podiumd_env, objecten_api)]
    type_url = objecttype_url(podiumd_env, make_granted_objecttype(podiumd_env, registry, SCHEMA, tokens))
    bsn = random_bsn()
    eigen = make_object(objecten, registry, type_url, {"bsn": bsn, "naam": "Oud"})
    vreemd = make_object(objecten, registry, type_url, {"bsn": random_bsn(), "naam": "Ander"})
    registry.add(
        f"objects of objecttype {type_url}",
        lambda: [objecten.delete(str(o["url"])) for o in objecten.list("objects", {"type": type_url})],
    )

    mapping = [{"variable_key": "naam", "target_path": ["naam"]}]
    prefill = {
        "objects_api_group": objecten_api,
        "objecttype_uuid": uuid_of(type_url),
        "objecttype_version": 1,
        "skip_ownership_check": False,
        "auth_attribute_path": OWNER,
        "variables_mapping": mapping,
    }
    variable = {"key": "object", "data_type": "object", "prefill_plugin": "objects_api", "prefill_options": prefill}
    options = {
        "version": 2,
        "objecttype": uuid_of(type_url),
        "objecttype_version": 1,
        "update_existing_object": True,
        "auth_attribute_path": OWNER,
        "variables_mapping": [*mapping, {"variable_key": "auth_bsn", "target_path": OWNER}],
        "transform_to_list": [],
        "upload_submission_csv": False,
        "iot_submission_report": "",
        "iot_submission_csv": "",
        "iot_attachment": "",
    }
    registration = {"backend": "objects_api", "objects_api": objecten_api, "options": options}
    slug = registry.tagged("object-wijzigen")
    make_form(podiumd_env, registry, slug, [NAAM], registration, ("digid_oidc",), variables=[variable])

    base = urls["openformulieren"]
    http = log_in_as(podiumd_env, registry, slug, "digid_oidc", {"bsn": [bsn]})
    submission, headers = start_submission(http, base, slug, initialDataReference=eigen["uuid"])
    forget_submission(podiumd_env, registry, str(submission["id"]))
    step = expect_status(http.get(str(entries(submission["steps"])[0]["url"])), HTTPStatus.OK).json()
    assert section(step, "data").get("naam") == "Oud"

    complete_submission(podiumd_env, http, submission, headers, {"naam": "Nieuw"}, timeout=TIMEOUT)
    record = section(objecten.get(str(eigen["url"])), "record")
    assert (record["index"], record["data"]) == (2, {"bsn": bsn, "naam": "Nieuw"})
    assert sorted(str(o["uuid"]) for o in objecten.list("objects", {"type": type_url})) == sorted(
        [str(eigen["uuid"]), str(vreemd["uuid"])]
    )
    # A new login: a submission takes the form's login along.
    again = log_in_as(podiumd_env, registry, slug, "digid_oidc", {"bsn": [bsn]})
    refused, _ = new_submission(again, base, slug, initialDataReference=vreemd["uuid"])
    assert refused.status_code == HTTPStatus.FORBIDDEN, refused.text
