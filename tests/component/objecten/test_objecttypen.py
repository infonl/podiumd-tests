"""The objecttypes KISS and ITA work with exist in Objecttypen, with a published newest version.

Ported from podiumd-minikube test_kiss_ita.py, by name instead of its fixed UUIDs: the estates
create these objecttypes themselves. The API tests read them as Objecten and the apps do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.bootstrap.names import ITA_OBJECTTYPES
from podiumd_tests.bootstrap.names import KISS_OBJECTTYPES
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.json_data import section
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.seed.objecten import named_objecttypes
from podiumd_tests.seed.objecten import newest_version

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("objecttypen"),
    pytest.mark.source(
        "MK test_kiss_ita.py", "Checks the objecttypes KISS and ITA work with are published in Objecttypen."
    ),
]


@pytest.mark.parametrize(
    "name",
    [requiring("ita", n, test_id=n) for n in ITA_OBJECTTYPES]
    + [requiring("kiss", n, test_id=n) for n in KISS_OBJECTTYPES],
)
@pytest.mark.requires("cluster")
@pytest.mark.scenario("""
    Given an objecttype that KISS or ITA works with
    When its versions are read in Objecttypen
    Then its newest version is published
""")
def test_objecttype_is_published(podiumd_env: Environment, name: str) -> None:
    """The objecttype exists and its newest version is published (a draft cannot hold objects)."""
    found = run_snippet(
        podiumd_env.kube, podiumd_env.deployment_for("objecttypen"), "objecttypen_versions", {"names": [name]}
    )
    assert cast("dict[str, str | None]", found)[name] == "published"


@pytest.mark.parametrize(
    "name",
    [requiring("ita", n, test_id=n) for n in ITA_OBJECTTYPES]
    + [requiring("kiss", n, test_id=n) for n in KISS_OBJECTTYPES],
)
@pytest.mark.scenario("""
    Given an objecttype that KISS or ITA works with
    When a client lists the objecttypes by its name in the Objecttypen API
    Then the API lists exactly one objecttype with that name
    And its newest version has a JSON schema
""")
def test_api_serves_the_objecttype_with_its_schema(objecttypen: ApiClient, name: str) -> None:
    """The API lists the objecttype once by name, and its newest version carries a JSON schema.

    Once: podiumd's create-required-objecttypen Job runs on every upgrade and must not create it again.
    """
    found = named_objecttypes(objecttypen, name)
    assert len(found) == 1, f"Objecttypen API lists {len(found)} objecttypes named {name}, expected 1"
    assert section(newest_version(objecttypen, found[0]), "jsonSchema"), f"{name}: newest version has no jsonSchema"
