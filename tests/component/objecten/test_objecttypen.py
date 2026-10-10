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
from podiumd_tests.json_data import strings
from podiumd_tests.pytest_plugin import requiring

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.requires("objecttypen")]


@pytest.mark.parametrize(
    "name",
    [requiring("ita", n, test_id=n) for n in ITA_OBJECTTYPES]
    + [requiring("kiss", n, test_id=n) for n in KISS_OBJECTTYPES],
)
@pytest.mark.requires("cluster")
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
def test_api_serves_the_objecttype_with_its_schema(objecttypen: ApiClient, name: str) -> None:
    """The API lists the objecttype by name, and its newest version carries a JSON schema."""
    found = [t for t in objecttypen.list("objecttypes", {"name": name}) if t.get("name") == name]
    assert found, f"Objecttypen API lists no objecttype {name}"
    versions = strings(found[0].get("versions"))
    newest = objecttypen.get(max(versions, key=lambda url: int(url.rstrip("/").rsplit("/", 1)[-1])))
    assert section(newest, "jsonSchema"), f"{name}: newest version has no jsonSchema"
