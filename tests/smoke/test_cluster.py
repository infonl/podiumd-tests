"""Are the workloads up and deployed with care? Ported from MK/PI test_pods.py (see workloads, hygiene)."""

from __future__ import annotations

import warnings

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.hygiene import baseline_violations
from podiumd_tests.hygiene import missing_requests
from podiumd_tests.hygiene import unpinned_images
from podiumd_tests.workloads import failed_jobs
from podiumd_tests.workloads import unhealthy_pods
from podiumd_tests.workloads import unready_workloads

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.smoke, pytest.mark.cluster, pytest.mark.requires("cluster")]

# The podiumd chart gives these containers `resources: {}`; KISS's Elasticsearch requests memory only.
KNOWN_WITHOUT_REQUESTS = (
    "openbeheer/openbeheer",
    "referentielijsten/referentielijsten",
    "kiss-es-default/elasticsearch",
)


def test_workloads_ready(podiumd_env: Environment) -> None:
    """Every Deployment and StatefulSet has all wanted replicas ready."""
    not_ready = unready_workloads(podiumd_env.workloads())
    assert not not_ready, f"not ready: {not_ready}"


def test_pods_healthy(podiumd_env: Environment) -> None:
    """Every long-running pod is Running with all containers ready (catches a stuck 1/2 sidecar)."""
    unhealthy = unhealthy_pods(podiumd_env.items("pods"))
    assert not unhealthy, f"unhealthy pods: {unhealthy}"


def test_jobs_succeeded(podiumd_env: Environment) -> None:
    """No setup Job failed, and the latest run of each CronJob did not fail."""
    failed = failed_jobs(podiumd_env.items("jobs"))
    assert not failed, f"failed jobs: {failed}"


def test_pods_meet_the_baseline_security_standard(podiumd_env: Environment) -> None:
    """No pod template uses host namespaces, host paths or ports, privileged mode or extra capabilities."""
    found = [v for w in podiumd_env.workloads() for v in baseline_violations(w)]
    assert not found, found


def test_images_are_pinned(podiumd_env: Environment) -> None:
    """Every image has a tag other than latest, or a digest, so a restart cannot change what runs."""
    found = [i for w in podiumd_env.workloads() for i in unpinned_images(w)]
    assert not found, found


def test_containers_request_cpu_and_memory(podiumd_env: Environment) -> None:
    """Every container requests CPU and memory, so the scheduler places it by size; KNOWN_WITHOUT_REQUESTS warn."""
    found = [m for w in podiumd_env.workloads() for m in missing_requests(w)]
    known = [m for m in found if m.split(":", 1)[0] in KNOWN_WITHOUT_REQUESTS]
    if known:
        warnings.warn(f"known containers without requests (PLAN §13): {known}", stacklevel=1)
    assert not set(found) - set(known), sorted(set(found) - set(known))
