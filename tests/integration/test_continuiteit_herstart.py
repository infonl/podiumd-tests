"""A component survives the loss of a pod and a rolling restart (hosting standards COMP006.1 and COMP006.2).

Each test deletes a pod or restarts the component's main Deployment while a light load asks its root; with two or
more replicas no call may fail, with one the root must answer again within the recovery time.
"""

from __future__ import annotations

import time

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.chaos_load import CALM
from podiumd_tests.chaos_load import failures
from podiumd_tests.chaos_load import loaded
from podiumd_tests.chaos_load import recovery_seconds
from podiumd_tests.chaos_load import root_call
from podiumd_tests.json_data import section
from podiumd_tests.kube import metadata_name
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.responses import is_root_answering
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import ROOT_TIMEOUT
from podiumd_tests.workloads import cluster_state
from podiumd_tests.workloads import disruptions
from podiumd_tests.workloads import pod_workload
from podiumd_tests.workloads import replace_pod

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.integration, pytest.mark.destructive, pytest.mark.requires("cluster")]

# The components whose main Deployment serves a public root.
RESTARTED = (
    "objecten",
    "objecttypen",
    "openarchiefbeheer",
    "openbeheer",
    "openformulieren",
    "openinwoner",
    "openklant",
    "opennotificaties",
    "openvtb",
    "openzaak",
    "referentielijsten",
    "kiss",
    "ita",
    "pabc",
    "omc",
    "zaakbrug",
    "zac",
)
# Seconds a component gets to run a ready replacement pod (ZAC starts in about 3 minutes).
RECOVERY = 420
STANDARD = pytest.mark.source(
    "hosting COMP006.1-stop-start-safe", "Application MUST be able to withstand sudden stops and starts."
)


def _replicas(env: Environment, deployment: str) -> int:
    found = env.kube.get_json("deployment", deployment)
    return int(str(section(found, "spec").get("replicas", 1)))


def _under_load(
    env: Environment, http: requests.Session, component: str, disrupt: Callable[[], None]
) -> tuple[list[str], float | None, list[str]]:
    """Run disrupt while a load asks the component's root; the failed calls, the recovery and other restarts."""
    url, deployment = env.profile.urls[component], env.deployment_for(component)
    before = cluster_state(env)
    with loaded({component: root_call(http, url)}, workers=2, pause=1) as load:
        load.run_for(CALM)
        start = time.time()
        disrupt()
        wait_until(
            lambda: is_root_answering(http, url, ROOT_TIMEOUT), timeout=RECOVERY, description=f"{component} answers"
        )
        load.run_for(CALM)
    restarted = [d.text for d in disruptions(before, cluster_state(env), {deployment})]
    return failures(load.attempts, start), recovery_seconds(load.attempts, start), restarted


@pytest.mark.parametrize("component", [requiring(c, c) for c in RESTARTED])
@STANDARD
@pytest.mark.scenario("""
    Given a component answers while a light load asks its root
    When one pod of its main Deployment is deleted
    Then the component answers again once a replacement pod is ready
    And no call fails when the Deployment runs two or more replicas
    And no container of another workload restarts
""")
def test_component_survives_the_loss_of_a_pod(
    podiumd_env: Environment,
    http: requests.Session,
    component: str,
    record_property: Callable[[str, object], None],
) -> None:
    """Deleting a pod of the main Deployment costs at most its own pod; with 2+ replicas no call fails."""
    deployment = podiumd_env.deployment_for(component)
    pod = next(p for p in podiumd_env.items("pods") if pod_workload(p) == deployment)
    failed, recovered, restarted = _under_load(
        podiumd_env, http, component, lambda: replace_pod(podiumd_env, pod, RECOVERY)
    )
    record_property("measured", {"recovery_seconds": recovered, "pod": metadata_name(pod)})
    assert restarted == []
    if _replicas(podiumd_env, deployment) >= 2:  # two replicas keep a component up
        assert failed == []


@pytest.mark.parametrize("component", [requiring(c, c) for c in RESTARTED])
@pytest.mark.source(
    "hosting COMP006.2-upgrade-time-limit",
    "Any upgrade of a component SHOULD be able to be performed in a rolling manner, with zero downtime.",
)
@pytest.mark.scenario("""
    Given a component's main Deployment runs two or more replicas
    And a light load asks the component's root
    When the Deployment is restarted in a rolling manner
    Then no call fails
""")
def test_rolling_restart_has_no_downtime(
    podiumd_env: Environment,
    http: requests.Session,
    component: str,
    record_property: Callable[[str, object], None],
) -> None:
    """A rolling restart of a Deployment with 2+ replicas loses no call of the load."""
    deployment = podiumd_env.deployment_for(component)
    replicas = _replicas(podiumd_env, deployment)
    if replicas < 2:  # a rolling restart of one replica always stops it for a moment
        pytest.skip(f"{deployment} runs {replicas} replica on {podiumd_env.profile.name}")
    failed, recovered, _ = _under_load(
        podiumd_env, http, component, lambda: podiumd_env.kube.roll_out(deployment, RECOVERY, restart=True)
    )
    record_property("measured", {"recovery_seconds": recovered, "replicas": replicas})
    assert failed == []
