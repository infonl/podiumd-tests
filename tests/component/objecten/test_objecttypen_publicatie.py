"""Objecttypen's rules for versions: a published version neither changes nor goes, nor does an objecttype with versions.

Every objecttype here is a run-tagged throwaway; cleanup deletes it with a Django snippet, since the API refuses to
delete a published version.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.responses import invalid_codes
from podiumd_tests.seed.objecten import ANY_OBJECT
from podiumd_tests.seed.objecten import make_objecttype
from podiumd_tests.seed.openzaak import today

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("objecttypen", "cluster"),
    pytest.mark.source(
        "upstream maykinmedia/open-object src/objects/tests/v2/test_validation.py, test_objecttypeversion_api.py",
        "Only a draft version changes or is deleted; an objecttype goes only without versions.",
    ),
]


@pytest.mark.scenario("""
    Given an objecttype in Objecttypen with a draft version
    When a client deletes the objecttype
    Then Objecttypen refuses it while the objecttype has versions
    And publishing the version makes it published as of today
""")
def test_draft_version_publishes(podiumd_env: Environment, objecttypen: ApiClient, registry: ResourceRegistry) -> None:
    """An objecttype with a version is not deleted; publishing a draft version sets its publishedAt."""
    version = make_objecttype(podiumd_env, objecttypen, registry, "draft")
    assert version["publishedAt"] is None
    refused = objecttypen.request("DELETE", str(version["objectType"]), HTTPStatus.BAD_REQUEST)
    assert invalid_codes(refused) == ["pending-versions"]
    published = objecttypen.patch(str(version["url"]), {"status": "published"})
    assert (published["status"], published["publishedAt"]) == ("published", today())


@pytest.mark.scenario("""
    Given an objecttype in Objecttypen with a published version
    When a client replaces or changes the version's JSON schema
    Then Objecttypen refuses it
    And it refuses to delete the version
    And the version keeps its JSON schema
""")
def test_published_version_neither_changes_nor_goes(
    podiumd_env: Environment, objecttypen: ApiClient, registry: ResourceRegistry
) -> None:
    """PUT, PATCH and DELETE of a published version answer 400."""
    url = str(make_objecttype(podiumd_env, objecttypen, registry, "published")["url"])
    changed = {"jsonSchema": {**ANY_OBJECT, "required": ["naam"]}}
    for method in ("PUT", "PATCH"):
        refused = objecttypen.request(method, url, HTTPStatus.BAD_REQUEST, json=changed)
        assert invalid_codes(refused) == ["non-draft-version-update"], method
    refused = objecttypen.request("DELETE", url, HTTPStatus.BAD_REQUEST)
    assert invalid_codes(refused) == ["non-draft-version-destroy"]
    assert objecttypen.get(url)["jsonSchema"] == ANY_OBJECT
