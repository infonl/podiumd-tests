"""Unit tests for judging workload health from kubectl JSON."""

import json

import pytest

from podiumd_tests.kube import Kube
from podiumd_tests.kube import KubeError
from podiumd_tests.workloads import component_versions
from podiumd_tests.workloads import failed_jobs
from podiumd_tests.workloads import run_cronjob
from podiumd_tests.workloads import scaled
from podiumd_tests.workloads import unhealthy_pods
from podiumd_tests.workloads import unready_workloads

WARMUP = {"name": "deploy-warmup", "labels": {"app": "deploy-warmup"}}


def pod(name, phase="Running", *, ready=True, owner="ReplicaSet", deleting=False):
    metadata = {"name": name, "ownerReferences": [{"kind": owner, "name": f"{name}-owner"}]}
    if deleting:
        metadata["deletionTimestamp"] = "2026-10-06T10:00:00Z"
    return {"metadata": metadata, "status": {"phase": phase, "containerStatuses": [{"name": "app", "ready": ready}]}}


def job(name, *, failed=False, cronjob=None, created="2026-10-06T10:00:00Z"):
    metadata = {"name": name, "creationTimestamp": created}
    if cronjob:
        metadata["ownerReferences"] = [{"kind": "CronJob", "name": cronjob}]
    conditions = [{"type": "Failed", "status": "True"}] if failed else [{"type": "Complete", "status": "True"}]
    return {"metadata": metadata, "status": {"conditions": conditions}}


def test_unready_workloads():
    items = [
        {"kind": "Deployment", "metadata": {"name": "zac"}, "spec": {"replicas": 1}, "status": {}},
        {"kind": "Deployment", "metadata": {"name": "off"}, "spec": {"replicas": 0}, "status": {}},
        {"kind": "StatefulSet", "metadata": {"name": "redis"}, "spec": {"replicas": 2}, "status": {"readyReplicas": 2}},
        {"kind": "Deployment", "metadata": WARMUP, "spec": {"replicas": 4}, "status": {"readyReplicas": 3}},
    ]
    assert unready_workloads(items) == ["Deployment/zac 0/1"]


def test_unhealthy_pods_skips_job_pods_and_terminating_pods():
    pods = [
        pod("ok"),
        pod("sidecar-down", ready=False),
        pod("pending", phase="Pending"),
        pod("config-xyz", phase="Failed", owner="Job"),
        pod("old", phase="Failed", deleting=True),
        {**pod("deploy-warmup-x", phase="Pending"), "metadata": WARMUP},
    ]
    assert unhealthy_pods(pods) == ["sidecar-down/app: not ready", "pending: phase Pending"]


def test_failed_jobs_counts_only_the_latest_cronjob_run():
    jobs = [
        job("setup", failed=True),
        job("setup-ok"),
        job("cron-1", failed=True, cronjob="cron", created="2026-10-06T09:00:00Z"),
        job("cron-2", cronjob="cron", created="2026-10-06T10:00:00Z"),
        job("other-1", failed=True, cronjob="other"),
    ]
    assert failed_jobs(jobs) == ["other-1", "setup"]


def test_scaled_restores_the_replicas_also_when_the_block_fails(fake_runner):
    fake_runner.answers = {"get deployment openzaak": (0, json.dumps({"spec": {"replicas": 2}})), "": (0, "")}
    with pytest.raises(RuntimeError), scaled(Kube("ctx", "podiumd", fake_runner), "openzaak", 0):
        raise RuntimeError
    rollout = ["rollout", "status", "deployment/openzaak", "--timeout=300s"]
    assert [c[5:] for c in fake_runner.calls[1:]] == [
        ["scale", "deployment/openzaak", "--replicas=0"],
        rollout,
        ["scale", "deployment/openzaak", "--replicas=2"],
        rollout,
    ]


def test_run_cronjob_deletes_the_job_also_when_it_does_not_complete(fake_runner):
    fake_runner.answers = {"wait": (1, "timed out"), "logs": (0, "Unauthorized"), "": (0, "")}
    with pytest.raises(KubeError, match="log of job/ptest-x:\nUnauthorized"):
        run_cronjob(Kube("ctx", "podiumd", fake_runner), "contact-vac-sync", "ptest-x")
    assert [c[5:8] for c in fake_runner.calls] == [
        ["create", "job", "ptest-x"],
        ["wait", "--for=condition=complete", "job/ptest-x"],
        ["logs", "job/ptest-x", "--tail=60"],
        ["delete", "job", "ptest-x"],
    ]


@pytest.mark.parametrize(
    ("image", "label", "version"),
    [("ita.web:3.3.2", "3.3.4", (3, 3, 2)), ("ita.web@sha256:0bef", "3.3.4", (3, 3, 4)), ("ita.web:latest", "", None)],
)
def test_component_versions_take_the_image_tag_else_the_helm_label(env_factory, fake_runner, image, label, version):
    ita = {
        "metadata": {"name": "ita-web", "labels": {"app.kubernetes.io/version": label}},
        "spec": {"template": {"spec": {"containers": [{"image": f"ghcr.io/ita/{image}"}]}}},
    }
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [ita]}))
    assert component_versions(env_factory(), ["ita", "zac"]).get("ita") == version
