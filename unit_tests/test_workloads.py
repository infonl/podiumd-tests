"""Unit tests for judging workload health from kubectl JSON."""

from podiumd_tests.workloads import failed_jobs
from podiumd_tests.workloads import unhealthy_pods
from podiumd_tests.workloads import unready_workloads


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
    ]
    assert unready_workloads(items) == ["Deployment/zac 0/1"]


def test_unhealthy_pods_skips_job_pods_and_terminating_pods():
    pods = [
        pod("ok"),
        pod("sidecar-down", ready=False),
        pod("pending", phase="Pending"),
        pod("config-xyz", phase="Failed", owner="Job"),
        pod("old", phase="Failed", deleting=True),
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
