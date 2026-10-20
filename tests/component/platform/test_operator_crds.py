"""Operator CRDs are in step with the operators. Ported from a helm-charts request.

PodiumD 4.10.0 needs CRD updates that `helm upgrade` never does (the Keycloak 26.8.1 CRD apply is required
before the upgrade). A forgotten apply or an old schema is invisible until an operator or a CR write fails.
This checks that every CRD of each operator's API group exists and is Established. The per-version schema
marker check is a separate, later addition. Skips where the credentials cannot list CRDs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import metadata_name

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.requires("cluster")]

# Operator Deployment name -> the API group whose CRDs it owns.
OPERATOR_GROUPS = {
    "keycloak-operator": "k8s.keycloak.org",
    "redis-operator": "redis.redis.opstreelabs.in",
}


def _established(crd: dict[str, object]) -> bool:
    conditions = entries(section(crd, "status").get("conditions"))
    return any(c.get("type") == "Established" and c.get("status") == "True" for c in conditions)


@pytest.mark.parametrize("operator", sorted(OPERATOR_GROUPS))
def test_operator_crds_are_established(podiumd_env: Environment, operator: str) -> None:
    """Every CRD of the operator's API group exists and is Established (the operator and its schema are in step)."""
    if operator not in podiumd_env.deployment_names:
        pytest.skip(f"{operator} is not deployed in this environment")
    try:
        crds = podiumd_env.kube.items("customresourcedefinitions")
    except KubeError as error:
        pytest.skip(f"cannot list CRDs: {error}")
    group = OPERATOR_GROUPS[operator]
    owned = [c for c in crds if section(c, "spec").get("group") == group]
    assert owned, f"{operator} runs but its API group {group} has no CRDs: run its install-*-crds.sh"
    not_ready = [metadata_name(c) for c in owned if not _established(c)]
    assert not not_ready, f"{operator} CRDs not Established: {not_ready}; run its install-*-crds.sh"
