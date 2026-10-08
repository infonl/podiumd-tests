"""The objecttypes KISS and ITA work with exist in Objecttypen, with a published newest version.

Ported from podiumd-minikube test_kiss_ita.py, by name instead of its fixed UUIDs: the estates
create these objecttypes themselves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.bootstrap.names import ITA_OBJECTTYPES
from podiumd_tests.bootstrap.names import KISS_OBJECTTYPES
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.pytest_plugin import requiring

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.requires("objecttypen", "cluster")]


@pytest.mark.parametrize(
    "name",
    [requiring("ita", n, test_id=n) for n in ITA_OBJECTTYPES]
    + [requiring("kiss", n, test_id=n) for n in KISS_OBJECTTYPES],
)
def test_objecttype_is_published(podiumd_env: Environment, name: str) -> None:
    """The objecttype exists and its newest version is published (a draft cannot hold objects)."""
    found = run_snippet(
        podiumd_env.kube, podiumd_env.deployment_for("objecttypen"), "objecttypen_versions", {"names": [name]}
    )
    assert cast("dict[str, str | None]", found)[name] == "published"
