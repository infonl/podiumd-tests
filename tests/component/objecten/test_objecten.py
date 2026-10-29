"""Objecten checks a record against its objecttype's JSON schema and keeps every record of an object.

Uses ITA's objecttype Afdeling (identificatie and naam required); the test's objects are run-tagged and deleted.
"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.seed.objecten import make_object
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openzaak import today

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("objecten", "cluster"),
]
POSTMAN = "upstream maykinmedia/objects-api docs/api/_assets/objects-api.postman_collection.json"

OBJECTTYPE = "Afdeling"


@pytest.fixture(name="afdeling_type")
def fixture_afdeling_type(podiumd_env: Environment) -> str:
    """The URL Objecten knows objecttype Afdeling by."""
    return objecttype_url(podiumd_env, OBJECTTYPE)


@pytest.mark.source(
    POSTMAN, "Create object (invalid): a record that does not match the objecttype's JSON schema is refused."
)
def test_record_breaking_the_objecttype_schema_is_refused(
    objecten: ApiClient, afdeling_type: str, registry: ResourceRegistry
) -> None:
    """A record without the required naam is refused with 400, and the error names the field."""
    record = {
        "typeVersion": 1,
        "data": {"identificatie": registry.tagged("afdeling")},
        "startAt": today(),
    }
    refused = objecten.request(
        "POST", "objects", HTTPStatus.BAD_REQUEST, json={"type": afdeling_type, "record": record}
    )
    body = refused.json()
    # Objecten 3.x answers with non_field_errors; Open Object 4.x with invalid_params.
    reasons = [str(p.get("reason")) for p in entries(body.get("invalid_params"))] + strings(
        body.get("non_field_errors")
    )
    assert any("'naam'" in r for r in reasons), body


@pytest.mark.source(
    POSTMAN, "An object's records stay available: its history, and the object on a date or registration date."
)
def test_changed_object_keeps_its_earlier_record(
    objecten: ApiClient, afdeling_type: str, registry: ResourceRegistry
) -> None:
    """A PATCH adds a record and ends the first; history lists both, and ?date= and ?registrationDate= read the past.

    Materiële historie: on a date before the change the object has its first record. Formele historie: before its
    registration the object did not exist.
    """
    now = date.fromisoformat(today())
    identificatie = registry.tagged("afdeling")
    created = make_object(
        objecten,
        registry,
        afdeling_type,
        {"identificatie": identificatie, "naam": "eerste"},
        start_at=(now - timedelta(days=10)).isoformat(),
    )
    url = str(created["url"])
    record = {
        "typeVersion": 1,
        "data": {"identificatie": identificatie, "naam": "tweede"},
        "startAt": now.isoformat(),
    }
    assert section(objecten.patch(url, {"record": record}), "record")["index"] == 2
    history = entries(objecten.request("GET", f"{url}/history", HTTPStatus.OK).json().get("results"))
    assert [(r["index"], section(r, "data")["naam"], r["endAt"]) for r in history] == [
        (1, "eerste", now.isoformat()),
        (2, "tweede", None),
    ]
    earlier = objecten.get(url, {"date": (now - timedelta(days=5)).isoformat()})
    assert section(section(earlier, "record"), "data")["naam"] == "eerste"
    before = {"registrationDate": (now - timedelta(days=1)).isoformat()}
    objecten.request("GET", url, HTTPStatus.NOT_FOUND, params=before)
