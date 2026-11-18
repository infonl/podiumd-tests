"""Every PodiumD component answers on each name of its Service in the cluster (hosting standards, DNS naming)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.components import COMPONENTS
from podiumd_tests.defects import DefectSymptomError
from podiumd_tests.defects import symptom
from podiumd_tests.hygiene import cluster_names
from podiumd_tests.mock_server import in_cluster_statuses

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.environment import Environment

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("cluster"),
    pytest.mark.source(
        "hosting DNS Naming Conventions",
        "Applications MUST be accessible via kubernetes internal DNS naming: openzaak.podiumd.svc.cluster.local.",
    ),
]

# Django refuses a host outside ALLOWED_HOSTS with 400 Bad Request.
HOST_REFUSED = 400
# Not PodiumD components: the mail catcher, and the inway, which serves only through Frank!Gateway.
LEFT_OUT = frozenset(("mailpit", "inway"))
FQDN = ".svc.cluster.local:"


@pytest.mark.xfail(
    strict=True,
    raises=DefectSymptomError,
    reason="[podiumd-chart-49] the estates' allowedHosts (minikube as ExternalsPodiumD, kees00) replace the podiumd"
    " default .svc.cluster.local: Django apps refuse <service>.podiumd.svc.cluster.local with 400 (Open Inwoner does not"
    " answer, open-inwoner-4); not reported upstream",
)
@pytest.mark.scenario("""
    Given the PodiumD components in the cluster
    When each is asked for its root by its Service's short name, with the namespace, and fully qualified
    Then each answers, with no 400 for an unknown host and no timeout
""")
def test_components_answer_on_their_cluster_names(
    podiumd_env: Environment, need_bootstrap: Callable[..., None]
) -> None:
    """GET / on each cluster DNS name of every component's Service, from the mock server's pod, gets an answer."""
    need_bootstrap("infra-mock-server")
    components = sorted(c for c in podiumd_env.profile.urls if c in COMPONENTS and c not in LEFT_OUT)
    urls = {url: component for component in components for url in cluster_names(podiumd_env, component)}
    statuses = in_cluster_statuses(podiumd_env, list(urls))
    refused = {url: status for url, status in statuses.items() if not isinstance(status, int) or status == HOST_REFUSED}
    # podiumd-chart-49 concerns the fully qualified name only.
    assert {url: status for url, status in refused.items() if FQDN not in url} == {}
    with symptom():
        assert refused == {}
