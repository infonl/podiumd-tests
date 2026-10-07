"""The Maykin apps: their database, and the local admin login.

Ported from podiumd-minikube and podiumd-infra test_database.py (portable: through each app's own
Django connection, not a postgres pod) and test_django_admin_login.py. Not ported: MK's check of
its own seeded zac_client secret (fixture data of podiumd-minikube).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.auth.django_admin import admin_login
from podiumd_tests.auth.django_admin import is_logged_in
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.pytest_plugin import requiring

if TYPE_CHECKING:
    from podiumd_tests.credentials import SecretResolver
    from podiumd_tests.environment import Environment

pytestmark = pytest.mark.component

DJANGO_APPS = (
    "openzaak",
    "openklant",
    "objecten",
    "objecttypen",
    "opennotificaties",
    "openformulieren",
    "openarchiefbeheer",
)
# Apps that store geometry; their database needs PostGIS.
SPATIAL = frozenset({"openzaak", "objecten"})


@pytest.mark.cluster
@pytest.mark.requires("cluster")
@pytest.mark.parametrize("component", [requiring(c, c) for c in DJANGO_APPS])
def test_database(podiumd_env: Environment, component: str) -> None:
    """The app reaches its PostgreSQL database; apps with geometry have PostGIS (MK/PI test_database.py)."""
    info = cast(
        "dict[str, object]", run_snippet(podiumd_env.kube, podiumd_env.deployment_for(component), "database", {})
    )
    assert info["vendor"] == "postgresql"
    if component in SPATIAL:
        assert "postgis" in cast("list[str]", info["extensions"])


@pytest.mark.parametrize("component", [requiring(c, c) for c in DJANGO_APPS])
def test_django_admin_login(podiumd_env: Environment, credentials: SecretResolver, component: str) -> None:
    """The app's superuser logs in to the admin (MK test_django_admin_login.py); environments with SSO only skip."""
    username, password = credentials.optional("django_admin_username"), credentials.optional("django_admin_password")
    if not username or not password:
        pytest.skip("no secrets django_admin_username/password: admin login goes through SSO here")
    response = admin_login(podiumd_env.session(), podiumd_env.profile.urls[component], username, password)
    assert is_logged_in(response, username), f"{component}: not logged in ({response.url})"
