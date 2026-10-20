"""Operator CRDs are in step with the operators. Ported from a helm-charts request.

PodiumD 4.10.0 needs CRD updates that `helm upgrade` never does (the Keycloak 26.8.1 CRD apply is required
before the upgrade). A forgotten apply or an old schema is invisible until an operator or a CR write fails.
Skips where the credentials cannot list CRDs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.crds import Marker
from podiumd_tests.crds import is_established
from podiumd_tests.crds import wrong_markers
from podiumd_tests.json_data import section
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import metadata_name
from podiumd_tests.workloads import image_version

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.requires("cluster")]

# Operator Deployment name -> the API group whose CRDs it owns.
OPERATOR_GROUPS = {
    "keycloak-operator": "k8s.keycloak.org",
    "redis-operator": "redis.redis.opstreelabs.in",
}
# The helm-charts script that installs an operator's CRDs for a version.
INSTALL_SCRIPTS = {
    "keycloak-operator": "charts/podiumd/scripts/install-keycloak-operator-crds.sh --keycloak-version {}",
    "redis-operator": "charts/podiumd/scripts/install-redis-operator-crds.sh --version {}",
}
_KC = OPERATOR_GROUPS["keycloak-operator"]
_REDIS = OPERATOR_GROUPS["redis-operator"]
# Fields each operator version introduced (or dropped), from diffs of the upstream CRDs.
# redis-operator 0.25.0 is its last schema change up to 0.27.
MARKERS = {
    "keycloak-operator": [
        Marker(f"keycloaks.{_KC}", (26, 8, 0), "spec.unsupported.podTemplate.spec.schedulingGroup"),
        Marker(f"keycloakrealmimports.{_KC}", (26, 8, 0), "spec.realm.identityProviders[].organizationLinks"),
        Marker(
            f"keycloakrealmimports.{_KC}", (26, 8, 0), "spec.realm.identityProviders[].organizationId", present=False
        ),
    ],
    "redis-operator": [
        *(
            Marker(f"{kind}.{_REDIS}", (0, 22, 0), "spec.kubernetesConfig.persistentVolumeClaimRetentionPolicy")
            for kind in ("redis", "redisclusters", "redisreplications", "redissentinels")
        ),
        Marker(f"redisreplications.{_REDIS}", (0, 23, 0), "spec.sentinel"),
        Marker(f"redisreplications.{_REDIS}", (0, 25, 0), "spec.sentinel.affinity"),
        *(
            Marker(f"{kind}.{_REDIS}", (0, 25, 0), "spec.podManagementPolicy")
            for kind in ("redisclusters", "redisreplications", "redissentinels")
        ),
    ],
}


def _owned_crds(env: Environment, operator: str) -> list[dict[str, object]]:
    if operator not in env.deployment_names:
        pytest.skip(f"{operator} is not deployed in this environment")
    try:
        crds = env.kube.items("customresourcedefinitions")
    except KubeError as error:
        pytest.skip(f"cannot list CRDs: {error}")
    group = OPERATOR_GROUPS[operator]
    owned = [c for c in crds if section(c, "spec").get("group") == group]
    assert owned, f"{operator} runs but its API group {group} has no CRDs: run its install-*-crds.sh"
    return owned


@pytest.mark.parametrize("operator", sorted(OPERATOR_GROUPS))
def test_operator_crds_are_established(podiumd_env: Environment, operator: str) -> None:
    """Every CRD of the operator's API group exists and is Established."""
    not_ready = [metadata_name(c) for c in _owned_crds(podiumd_env, operator) if not is_established(c)]
    assert not not_ready, f"{operator} CRDs not Established: {not_ready}; run its install-*-crds.sh"


@pytest.mark.parametrize("operator", sorted(MARKERS))
def test_operator_crd_schemas_match_the_operator_version(podiumd_env: Environment, operator: str) -> None:
    """The CRDs' storage schemas have the fields of the running operator's image version."""
    owned = _owned_crds(podiumd_env, operator)
    version = image_version(podiumd_env.kube.get_json("deployment", operator))
    if version is None:
        pytest.skip(f"{operator} image has no version tag")
    wrong = wrong_markers(owned, MARKERS[operator], version)
    running = ".".join(map(str, version))
    script = INSTALL_SCRIPTS[operator].format(running)
    assert not wrong, f"{operator} {running} CRDs are older: {'; '.join(wrong)}; run {script}"
