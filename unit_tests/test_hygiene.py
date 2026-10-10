"""Unit tests for the deployment hygiene checks."""

from podiumd_tests.hygiene import baseline_violations
from podiumd_tests.hygiene import missing_requests
from podiumd_tests.hygiene import unpinned_images

REQUESTS = {"requests": {"cpu": "100m", "memory": "128Mi"}}


def workload(pod=None, containers=None, init=None):
    spec = {"containers": containers or [{"name": "app", "image": "ghcr.io/x/app:1.2.3", "resources": REQUESTS}]}
    if init:
        spec["initContainers"] = init
    return {"metadata": {"name": "w"}, "spec": {"template": {"spec": {**spec, **(pod or {})}}}}


def test_a_plain_workload_has_no_findings():
    assert baseline_violations(workload()) == []
    assert unpinned_images(workload()) == []
    assert missing_requests(workload()) == []


def test_baseline_violations():
    found = baseline_violations(
        workload(
            pod={"hostNetwork": True, "volumes": [{"name": "root", "hostPath": {"path": "/"}}]},
            containers=[
                {
                    "name": "app",
                    "image": "a:1",
                    "securityContext": {"privileged": True, "capabilities": {"add": ["NET_BIND_SERVICE", "SYS_ADMIN"]}},
                    "ports": [{"containerPort": 80, "hostPort": 80}],
                }
            ],
        )
    )
    assert found == [
        "w: hostNetwork",
        "w: hostPath volume root",
        "w/app: privileged",
        "w/app: adds capabilities ['SYS_ADMIN']",
        "w/app: hostPort 80",
    ]


def test_images_need_a_tag_or_digest_and_not_latest():
    containers = [
        {"name": "a", "image": "nginx"},
        {"name": "b", "image": "nginx:latest"},
        {"name": "c", "image": "registry:5000/nginx"},
        {"name": "d", "image": "nginx@sha256:abc"},
        {"name": "e", "image": "registry:5000/nginx:1.27"},
    ]
    found = unpinned_images(workload(containers=containers, init=[{"name": "i", "image": "busybox"}]))
    assert found == ["w/i: busybox", "w/a: nginx", "w/b: nginx:latest", "w/c: registry:5000/nginx"]


def test_requests_are_checked_on_containers_only():
    containers = [{"name": "a", "image": "a:1", "resources": {}}, {"name": "b", "image": "b:1", "resources": REQUESTS}]
    found = missing_requests(workload(containers=containers, init=[{"name": "i", "image": "i:1"}]))
    assert found == ["w/a: no cpu or memory request"]
