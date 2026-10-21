"""Redis HA: redis-ha-master points at exactly the pod that is Redis' master."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import section
from podiumd_tests.kube import metadata_name
from podiumd_tests.redis import MASTER_LABEL
from podiumd_tests.redis import MASTER_SERVICE
from podiumd_tests.redis import checks_master_role
from podiumd_tests.redis import ready_endpoints
from podiumd_tests.redis import redis_pods
from podiumd_tests.redis import reported_role

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("cluster"),
    pytest.mark.source(
        "podiumd-tests",
        "helm-charts #634 (IN-2961): a stale master label on a replica must not make redis-ha-master point at a slave.",
    ),
]


def test_redis_ha_master_service_points_at_the_master(podiumd_env: Environment) -> None:
    """redis-ha-master has one ready endpoint, that pod reports role:master, and no master-labelled pod is a slave.

    The redis-operator skips NotReady pods when it fixes role labels, so a stale master label can stay on a replica;
    the readiness check of helm-charts #634 (masterReadinessCheck) keeps such a pod out of redis-ha-master.
    """
    pods = redis_pods(podiumd_env)
    if not pods:
        pytest.skip("no redis-ha pods")
    if not all(checks_master_role(p) for p in pods):
        pytest.skip("redis-ha has no masterReadinessCheck (helm-charts #634)")
    roles = {metadata_name(p): reported_role(podiumd_env, p) for p in pods}
    behind = ready_endpoints(podiumd_env, MASTER_SERVICE)
    assert len(behind) == 1, f"{MASTER_SERVICE} ready endpoints: {behind}"
    assert roles[behind[0]] == "master", roles
    labelled = [
        metadata_name(p) for p in pods if section(section(p, "metadata"), "labels").get(MASTER_LABEL) == "master"
    ]
    assert [p for p in labelled if roles[p] != "master"] == [], roles
