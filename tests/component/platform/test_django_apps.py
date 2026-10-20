"""The Maykin apps: their database, their zgw_consumers Services, and the local admin login.

Ported from podiumd-minikube and podiumd-infra test_database.py (portable: through each app's own
Django connection, not a postgres pod) and test_django_admin_login.py. Not ported: MK's check of
its own seeded zac_client secret (fixture data of podiumd-minikube). The Service checks extend PI
test_zgw_service_reachability.py with each Service's credentials.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.auth.django_admin import admin_login
from podiumd_tests.auth.django_admin import is_logged_in
from podiumd_tests.components import DJANGO_APPS
from podiumd_tests.components import ZGW_CONSUMER_APPS
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.zgw_services import SERVICE_REFERENCES
from podiumd_tests.zgw_services import reference_problems
from podiumd_tests.zgw_services import service_problems

if TYPE_CHECKING:
    from podiumd_tests.credentials import SecretResolver
    from podiumd_tests.environment import Environment

pytestmark = pytest.mark.component

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


OBJECTEN_AUTORISATIES = (
    "[externalspodiumd-4] Objecten's zgw_consumers Service autorisaties-api (client_id objecten) carries a secret"
    " that matches no Open Zaak credential, so Open Zaak answers 403; no Objecten config field references it"
)


@pytest.mark.cluster
@pytest.mark.requires("cluster")
@pytest.mark.parametrize("component", [requiring(c, c) for c in ZGW_CONSUMER_APPS])
def test_zgw_services_authenticate(podiumd_env: Environment, component: str) -> None:
    """Every API the app has configured (zgw_consumers Service) lists with the Service's own credentials (PI)."""
    problems = service_problems(podiumd_env, component)
    # Objecttypen runs in the objecten deployment.
    if (
        component in {"objecten", "objecttypen"}
        and problems
        and all(p.startswith("autorisaties-api ") for p in problems)
    ):
        pytest.xfail(OBJECTEN_AUTORISATIES)
    assert problems == []


@pytest.mark.cluster
@pytest.mark.requires("cluster")
@pytest.mark.parametrize("component", [requiring(c, c) for c in SERVICE_REFERENCES])
def test_config_references_services(podiumd_env: Environment, component: str) -> None:
    """The app's config fields that PodiumD sets reference a Service in every row."""
    assert reference_problems(podiumd_env, component) == []


@pytest.mark.parametrize("component", [requiring(c, c) for c in DJANGO_APPS])
def test_django_admin_login(podiumd_env: Environment, credentials: SecretResolver, component: str) -> None:
    """The app's superuser logs in to the admin (MK test_django_admin_login.py); environments with SSO only skip."""
    if component in podiumd_env.profile.settings.get("django_admin_sso_only", "").split(","):
        pytest.skip(f"{component}'s admin logs in through Keycloak only (settings.django_admin_sso_only)")
    username, password = credentials.optional("django_admin_username"), credentials.optional("django_admin_password")
    if not username or not password:
        pytest.skip("no secrets django_admin_username/password: admin login goes through SSO here")
    response = admin_login(podiumd_env.session(), podiumd_env.profile.urls[component], username, password)
    assert is_logged_in(response, username), f"{component}: not logged in ({response.url})"
