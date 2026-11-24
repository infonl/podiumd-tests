"""Unit tests for judging workload health from kubectl JSON."""

import base64
import gzip
import json
import subprocess

from types import SimpleNamespace

import pytest

from podiumd_tests import workloads
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kube import Kube
from podiumd_tests.kube import KubeError
from podiumd_tests.workloads import SCALED_FROM
from podiumd_tests.workloads import ClusterState
from podiumd_tests.workloads import Operated
from podiumd_tests.workloads import chart_version
from podiumd_tests.workloads import component_versions
from podiumd_tests.workloads import cronjob_ending
from podiumd_tests.workloads import deployed_build
from podiumd_tests.workloads import disruptions
from podiumd_tests.workloads import failed_jobs
from podiumd_tests.workloads import is_chart_older_than
from podiumd_tests.workloads import is_scaled_to
from podiumd_tests.workloads import operated
from podiumd_tests.workloads import operated_down
from podiumd_tests.workloads import recreate_update_jobs
from podiumd_tests.workloads import release_object
from podiumd_tests.workloads import replica_drift
from podiumd_tests.workloads import rerun_job
from podiumd_tests.workloads import run_cronjob
from podiumd_tests.workloads import scaled
from podiumd_tests.workloads import scaled_leftovers
from podiumd_tests.workloads import skip_older_than
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
        pod("done", phase="Succeeded", ready=False),
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


def keycloak(name, message):
    condition = {"type": "RecreateUpdateUsed", "status": "True", "message": message}
    return {"metadata": {"name": name}, "status": {"conditions": [condition]}}


def test_failed_jobs_skips_an_update_job_that_asked_for_a_recreate():
    keycloaks = [
        keycloak("keycloak", "Incompatible changes detected. Check update job for details."),
        keycloak("other", "Unexpected update-compatibility command exit code (1). Check update job for details."),
    ]
    assert recreate_update_jobs(keycloaks) == {"keycloak-update-job"}
    jobs = [job("keycloak-update-job", failed=True), job("other-update-job", failed=True)]
    assert failed_jobs(jobs, keycloaks) == ["other-update-job"]


def test_failed_jobs_skips_the_minor_hop_update_job_once_keycloak_is_ready():
    message = "Unexpected update-compatibility command exit code (1). Check update job for details."
    conditions = [
        {"type": "RecreateUpdateUsed", "status": "True", "message": message},
        {"type": "Ready", "status": "True"},
    ]
    hop = {"metadata": {"name": "keycloak"}, "status": {"conditions": conditions}}
    assert failed_jobs([job("keycloak-update-job", failed=True)], [hop]) == []


class ScalingRunner:
    """kubectl on workloads that run the replicas they were last scaled to, all ready; lists `items` per kind."""

    def __init__(self, replicas, items=None):
        self.replicas: dict[str, int] = dict(replicas)
        self.items: dict[str, list[object]] = items or {}
        self.calls: list[list[str]] = []

    def __call__(self, args, _timeout, _stdin=None):
        self.calls.append(list(args))
        verb, target = args[5], args[6]
        out = ""
        if verb == "scale":
            self.replicas[target] = int(args[7].removeprefix("--replicas="))
        elif verb == "get" and target in self.replicas:
            count = self.replicas[target]
            status = {"replicas": count, "readyReplicas": count}
            out = json.dumps({"spec": {"replicas": count}, "status": status})
        elif verb == "get":
            out = json.dumps({"items": self.items.get(target, [])})
        return subprocess.CompletedProcess(list(args), 0, out, "")


def test_scaled_records_and_restores_the_replicas_also_when_the_block_fails(monkeypatch):
    monkeypatch.setattr(workloads, "new_run_id", lambda: "2610071230abcd")
    runner = ScalingRunner({"deployment/openzaak": 2})
    with pytest.raises(RuntimeError), scaled(Kube("ctx", "podiumd", runner), "deployment/openzaak", 0):
        raise RuntimeError
    changes = [c[5:] for c in runner.calls if c[5] != "get"]
    assert changes == [
        ["annotate", "--overwrite", "deployment/openzaak", f"{SCALED_FROM}=ptest-2610071230abcd 2"],
        ["scale", "deployment/openzaak", "--replicas=0"],
        ["scale", "deployment/openzaak", "--replicas=2"],
        ["annotate", "deployment/openzaak", f"{SCALED_FROM}-"],
    ]


@pytest.mark.parametrize(
    ("status", "metadata", "expected"),
    [
        ({"replicas": 3, "readyReplicas": 3, "observedGeneration": 2}, {"generation": 2}, True),
        ({"replicas": 3, "readyReplicas": 2, "observedGeneration": 2}, {"generation": 2}, False),
        ({"replicas": 3, "readyReplicas": 3, "observedGeneration": 1}, {"generation": 2}, False),
        ({}, {}, False),
    ],
    ids=["ready", "one-unready", "spec-unseen", "no-status"],
)
def test_is_scaled_to_needs_the_seen_spec_and_every_pod_ready(status, metadata, expected):
    assert is_scaled_to({"metadata": metadata, "status": status}, 3) is expected
    assert is_scaled_to({"metadata": {}, "status": {}}, 0)


def workload(kind, name, *, owner=None, scaled_from=None):
    metadata = {"name": name, "namespace": "podiumd"}
    if owner:
        metadata["ownerReferences"] = [{"kind": owner, "name": name}]
    if scaled_from:
        metadata["annotations"] = {SCALED_FROM: scaled_from}
    return {"kind": kind, "metadata": metadata}


def test_scaled_leftovers_lists_statefulsets_first(env_factory, fake_runner):
    fake_runner.answers = {
        "get deployments": (
            0,
            json.dumps({"items": [workload("Deployment", "solr-operator", scaled_from="ptest-x 1")]}),
        ),
        "get statefulsets": (
            0,
            json.dumps(
                {"items": [workload("StatefulSet", "solr", scaled_from="ptest-x 3"), workload("StatefulSet", "kc")]}
            ),
        ),
    }
    assert scaled_leftovers(env_factory()) == [
        ("statefulset/solr", "ptest-x", 3),
        ("deployment/solr-operator", "ptest-x", 1),
    ]


def test_operated_down_stops_the_operator_first_and_starts_it_last(env_factory):
    items = {
        "statefulsets": [
            workload("StatefulSet", "zac-solr-solrcloud", owner="SolrCloud"),
            workload("StatefulSet", "kc"),
        ],
        "deployments": [workload("Deployment", "solr-operator")],
    }
    runner = ScalingRunner({"deployment/solr-operator": 1, "statefulset/zac-solr-solrcloud": 3}, items)
    env = env_factory(runner=runner)
    assert operated(env, "RedisReplication", "redis-operator") is None
    target = operated(env, "SolrCloud", "solr-operator")
    assert target == Operated("zac-solr-solrcloud", "solr-operator")
    assert target is not None
    with operated_down(env.kube, target, 60):
        assert set(runner.replicas.values()) == {0}
    scales = [c[6:8] for c in runner.calls if c[5] == "scale"]
    assert scales == [
        ["deployment/solr-operator", "--replicas=0"],
        ["statefulset/zac-solr-solrcloud", "--replicas=0"],
        ["statefulset/zac-solr-solrcloud", "--replicas=3"],
        ["deployment/solr-operator", "--replicas=1"],
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


def test_rerun_job_copies_the_jobs_spec_without_its_controller_labels(fake_runner):
    source = {
        "spec": {
            "selector": {"matchLabels": {"controller-uid": "u1"}},
            "template": {
                "metadata": {"labels": {"controller-uid": "u1", "job-name": "ensure", "app": "kc"}},
                "spec": {"containers": [{"name": "c"}]},
            },
        }
    }
    fake_runner.answers = {"": (0, "")}
    rerun_job(Kube("ctx", "podiumd", fake_runner), source, "ptest-ensure", 60)
    applied = json.loads(next(stdin for stdin in fake_runner.stdins if stdin))
    assert applied["metadata"] == {"name": "ptest-ensure"}
    assert "selector" not in applied["spec"]
    assert applied["spec"]["template"]["metadata"] == {"labels": {"app": "kc"}}
    assert [c[5:8] for c in fake_runner.calls][-2:] == [
        ["wait", "--for=condition=complete", "job/ptest-ensure"],
        ["delete", "job", "ptest-ensure"],
    ]


@pytest.mark.parametrize(
    ("image", "label", "version"),
    [
        ("ita.web:3.3.2", "3.3.4", (3, 3, 2)),
        ("ita.web:3.3.2@sha256:0bef", "3.3.4", (3, 3, 2)),
        ("ita.web@sha256:0bef", "3.3.4", (3, 3, 4)),
        ("ita.web:v3.3.2", "3.3.4", (3, 3, 2)),
        ("ita.web:latest", "", None),
    ],
)
def test_component_versions_take_the_image_tag_else_the_helm_label(env_factory, fake_runner, image, label, version):
    ita = {
        "metadata": {"name": "ita-web", "labels": {"app.kubernetes.io/version": label}},
        "spec": {"template": {"spec": {"containers": [{"image": f"registry:5000/ita/{image}"}]}}},
    }
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [ita]}))
    assert component_versions(env_factory(), ["ita", "zac"]).get("ita") == version


def test_component_versions_read_release_of_an_image_pinned_by_digest(env_factory, fake_runner):
    """A digest-only image: its own RELEASE wins over the sub-chart's appVersion label."""
    ita = {
        "metadata": {"name": "ita-web", "labels": {"app.kubernetes.io/version": "3.3.2"}},
        "spec": {"template": {"spec": {"containers": [{"image": "ghcr.io/ita/ita.web@sha256:0bef"}]}}},
    }
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [ita]}))
    fake_runner.answers["RELEASE:-$VERSION_NUMBER"] = (0, "3.3.4\n")
    assert component_versions(env_factory(), ["ita"]).get("ita") == (3, 3, 4)


@pytest.mark.parametrize(
    ("answers", "version"),
    [
        ({"RELEASE:-$VERSION_NUMBER": (0, "\n"), "open_inwoner.__version__": (0, "warning\nv2.4.9\n")}, (2, 4, 9)),
        ({"RELEASE:-$VERSION_NUMBER": (0, "\n"), "open_inwoner.__version__": (1, "ImportError")}, (2, 4, 3)),
    ],
)
def test_open_inwoner_states_its_version_in_its_package(env_factory, fake_runner, answers, version):
    """Open Inwoner's RELEASE is empty: its package's __version__ wins over the stale sub-chart label."""
    openinwoner = {
        "metadata": {"name": "openinwoner", "labels": {"app.kubernetes.io/version": "2.4.3"}},
        "spec": {"template": {"spec": {"containers": [{"image": "maykinmedia/open-inwoner@sha256:ae87"}]}}},
    }
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [openinwoner]}))
    fake_runner.answers.update(answers)
    assert component_versions(env_factory(), ["openinwoner"]).get("openinwoner") == version


def test_chart_version_comes_from_podiumds_own_config_maps(env_factory, fake_runner):
    other = {"metadata": {"labels": {"app.kubernetes.io/name": "openzaak", "app.kubernetes.io/version": "1.20.0"}}}
    podiumd = {"metadata": {"labels": {"app.kubernetes.io/name": "podiumd", "app.kubernetes.io/version": "4.10.0"}}}
    fake_runner.answers["get configmaps"] = (0, json.dumps({"items": [other, podiumd]}))
    assert chart_version(env_factory()) == "4.10.0"
    fake_runner.answers["get configmaps"] = (0, json.dumps({"items": [other]}))
    assert chart_version(env_factory()) is None
    fake_runner.answers["get configmaps"] = (1, "connection refused")
    assert chart_version(env_factory()) is None


@pytest.mark.parametrize(("label", "older"), [("4.9.3", True), ("4.10.0", False), ("4.10.1", False), ("main", True)])
def test_chart_older_than_holds_also_for_an_unknown_version(env_factory, fake_runner, label, older):
    podiumd = {"metadata": {"labels": {"app.kubernetes.io/name": "podiumd", "app.kubernetes.io/version": label}}}
    fake_runner.answers["get configmaps"] = (0, json.dumps({"items": [podiumd]}))
    assert is_chart_older_than(env_factory(), (4, 10, 0)) is older


def test_deployed_build_reads_the_one_line_entries_of_the_configmap_in_the_setting(
    env_factory, fake_runner, profile_factory
):
    data = {"podiumd": "4.10.0", "monitoring-logging": "checkout x (f054)", "charts": json.dumps({"chart": "x" * 300})}
    fake_runner.answers["get configmap deployed"] = (0, json.dumps({"data": data}))
    profile = profile_factory(settings={"deployed_build": "ns/deployed"})
    assert deployed_build(env_factory(profile)) == {"podiumd": "4.10.0", "monitoring-logging": "checkout x (f054)"}
    assert deployed_build(env_factory()) == {}
    fake_runner.answers["get configmap deployed"] = (1, "not found")
    assert deployed_build(env_factory(profile)) == {}


def placed_pod(uid, name, *, node="n1", restarts=0, created="2026-10-15T09:51:00Z"):
    container = {
        "name": "app",
        "restartCount": restarts,
        "lastState": {"terminated": {"reason": "OOMKilled", "finishedAt": "2026-10-15T09:52:00Z"}} if restarts else {},
    }
    return {
        "metadata": {"uid": uid, "name": name, "creationTimestamp": created},
        "spec": {"nodeName": node},
        "status": {"containerStatuses": [container]},
    }


def test_disruptions_name_moved_pods_restarts_and_nodes():
    before = ClusterState({"a": placed_pod("a", "keycloak-0"), "b": placed_pod("b", "zac-1")}, frozenset(("n1", "n2")))
    after = ClusterState(
        {
            "c": placed_pod("c", "keycloak-0", node="n1", created="2026-10-15T09:52:10Z"),
            "b": placed_pod("b", "zac-1", restarts=1),
        },
        frozenset(("n1",)),
    )
    assert disruptions(before, after) == [
        ("", "node n2 removed"),
        ("", "pod keycloak-0 on n1 gone"),
        ("2026-10-15T09:52:10Z", "pod keycloak-0 on n1 started 2026-10-15T09:52:10Z"),
        ("2026-10-15T09:52:00Z", "container zac-1/app restarted 1x (last: OOMKilled at 2026-10-15T09:52:00Z)"),
    ]


def test_an_unchanged_cluster_has_no_disruptions():
    state = ClusterState({"a": placed_pod("a", "zac-1")}, frozenset(("n1",)))
    assert disruptions(state, state) == []


def _release_secret(manifest: str) -> dict[str, object]:
    """A Helm release Secret as Helm stores it: base64 of gzipped JSON, base64-encoded again by Kubernetes."""
    release = base64.b64encode(gzip.compress(json.dumps({"namespace": "podiumd", "manifest": manifest}).encode()))
    return {"data": {"release": base64.b64encode(release).decode()}}


MANIFEST = """
kind: Deployment
metadata: {name: openzaak}
spec: {replicas: 2}
---
kind: Deployment
metadata: {name: objecten}
spec: {replicas: 1}
---
kind: Deployment
metadata: {name: opentelemetry-collector}
---
kind: StatefulSet
metadata: {name: clamav, namespace: podiumd}
spec: {replicas: 1}
---
kind: Service
metadata: {name: openzaak}
"""


def test_release_object_finds_a_job_the_cluster_no_longer_has(env_factory, fake_runner):
    job = "\n---\nkind: Job\nmetadata: {name: ensure-keycloak-operator-sa}\nspec: {template: {}}\n"
    fake_runner.answers["get secrets"] = (0, json.dumps({"items": [_release_secret(MANIFEST + job)]}))
    env = env_factory()
    found = release_object(env, "Job", "ensure-keycloak-operator-sa")
    assert found is not None
    assert found["spec"] == {"template": {}}
    assert release_object(env, "Job", "absent") is None


def test_replica_drift_names_workloads_that_differ_from_their_helm_release(env_factory, fake_runner):
    def workload(kind, name, replicas):
        return {"kind": kind, "metadata": {"name": name, "namespace": "podiumd"}, "spec": {"replicas": replicas}}

    fake_runner.answers["get secrets"] = (0, json.dumps({"items": [_release_secret(MANIFEST)]}))
    deployments = [workload("Deployment", "openzaak", 2), workload("Deployment", "objecten", 0)]
    # keycloak-operator is in no release (an operator's own); opentelemetry-collector's release sets no replicas.
    deployments.extend(workload("Deployment", name, 0) for name in ("keycloak-operator", "opentelemetry-collector"))
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": deployments}))
    fake_runner.answers["get statefulsets"] = (0, json.dumps({"items": [workload("StatefulSet", "clamav", 0)]}))
    hpa = {"metadata": {"namespace": "podiumd"}, "spec": {"scaleTargetRef": {"kind": "StatefulSet", "name": "clamav"}}}
    fake_runner.answers["get horizontalpodautoscalers"] = (0, json.dumps({"items": [hpa]}))
    assert replica_drift(env_factory()) == ["Deployment/objecten 0 (Helm 1)"]


@pytest.mark.parametrize(("version", "xfail"), [((1, 26, 19), True), ((1, 27, 0), False), (None, False)])
def test_expect_defect_marks_only_an_affected_known_version(monkeypatch, version, xfail):
    monkeypatch.setattr(
        workloads, "component_versions", lambda _env, _c: {} if version is None else {"zaakbrug": version}
    )
    markers = []
    request = SimpleNamespace(applymarker=markers.append)
    workloads.expect_defect(request, None, "zaakbrug", lambda v: v < (1, 27, 0), raises=AssertionError, reason="r")  # pyright: ignore[reportArgumentType]
    strict = [True] if xfail else []
    assert [m.kwargs.get("strict") for m in markers] == strict


@pytest.mark.parametrize(("version", "skipped"), [((5, 9, 0), True), ((5, 9, 1), False), (None, False)])
def test_skip_older_than_runs_a_newer_or_unknown_version(monkeypatch, env_factory, version, skipped):
    found = {} if version is None else {"zac": version}
    monkeypatch.setattr(workloads, "component_versions", lambda _env, _components: found)
    if skipped:
        with pytest.raises(pytest.skip.Exception, match=r"zac 5\.9\.0 is older than 5\.9\.1: rules"):
            skip_older_than(env_factory(), "zac", (5, 9, 1), "rules")
    else:
        skip_older_than(env_factory(), "zac", (5, 9, 1), "rules")


def test_one_off_job_sets_env_in_each_container():
    container = {"name": "c", "env": [{"name": "POLLER_MODE", "value": "nieuw"}, {"name": "A", "value": "1"}]}
    pod = {"containers": [container]}
    cronjob = {"metadata": {"namespace": "podiumd"}, "spec": {"jobTemplate": {"spec": {"template": {"spec": pod}}}}}
    job = workloads.one_off_job(cronjob, "run-1", {"POLLER_MODE": "herinnering"})
    assert (job["kind"], job["metadata"]) == ("Job", {"name": "run-1", "namespace": "podiumd"})
    copied = entries(section(section(section(job, "spec"), "template"), "spec").get("containers"))[0]
    assert copied["env"] == [{"name": "A", "value": "1"}, {"name": "POLLER_MODE", "value": "herinnering"}]
    assert container["env"] == [{"name": "POLLER_MODE", "value": "nieuw"}, {"name": "A", "value": "1"}]


def test_cronjob_ending_finds_the_cronjob_or_none():
    env = SimpleNamespace(items=lambda _kind: [{"metadata": {"name": n}} for n in ("zac-sig-del", "zac-signaleren")])
    assert cronjob_ending(env, "-signaleren") == "zac-signaleren"  # pyright: ignore[reportArgumentType]
    assert cronjob_ending(env, "-x") is None  # pyright: ignore[reportArgumentType]


def owned_pod(uid, name, owner, kind="ReplicaSet"):
    found = placed_pod(uid, name)
    return {**found, "metadata": {**found["metadata"], "ownerReferences": [{"kind": kind, "name": owner}]}}


def test_pod_workload_names_the_deployment_statefulset_or_daemonset():
    assert workloads.pod_workload(owned_pod("a", "openzaak-7d9-x", "openzaak-7d9")) == "openzaak"
    assert workloads.pod_workload(owned_pod("b", "keycloak-0", "keycloak", "StatefulSet")) == "keycloak"
    assert workloads.pod_workload(owned_pod("c", "job-x", "job", "Job")) is None


def test_disruptions_leave_out_the_workloads_stopped_on_purpose():
    before = ClusterState({"a": owned_pod("a", "keycloak-0", "keycloak", "StatefulSet")}, frozenset(("n1",)))
    after = ClusterState({"b": owned_pod("b", "keycloak-0", "keycloak", "StatefulSet")}, frozenset(("n1",)))
    assert disruptions(before, after, {"keycloak"}) == []
    assert len(disruptions(before, after)) == 2


def test_worker_deployment_is_the_main_deployment_with_worker(env_factory):
    env = env_factory()
    env.__dict__["deployment_names"] = ["openformulieren", "openformulieren-worker", "openzaak"]
    assert workloads.worker_deployment(env, "openformulieren") == "openformulieren-worker"
    assert workloads.worker_deployment(env, "openzaak") is None


def _database_env(env_factory, host, *, from_config_map=False):
    env = env_factory()
    variables = (
        {"envFrom": [{"configMapRef": {"name": "openzaak"}}]}
        if from_config_map
        else {"env": [{"name": "DB_HOST", "value": host}]}
    )
    container = {"name": "openzaak", **variables}
    deployment = {"metadata": {"name": "openzaak"}, "spec": {"template": {"spec": {"containers": [container]}}}}
    endpoints = {"metadata": {"name": "postgres"}, "subsets": [{"addresses": [{"targetRef": {"name": "postgres-1"}}]}]}
    objects = {
        "deployments": [deployment],
        "configmaps": [{"metadata": {"name": "openzaak"}, "data": {"DB_HOST": host}}],
        "endpoints": [endpoints],
        "pods": [{"metadata": {"name": "postgres-1"}}, {"metadata": {"name": "openzaak-1"}}],
    }
    env.__dict__["deployment_names"] = ["openzaak"]
    env.__dict__["items"] = lambda kind: objects.get(kind, [])
    return env


def test_database_pod_is_the_pod_behind_open_zaaks_db_host(env_factory):
    assert workloads.database_pod(_database_env(env_factory, "postgres")) == {"metadata": {"name": "postgres-1"}}
    assert workloads.database_pod(_database_env(env_factory, "postgres", from_config_map=True)) is not None
    assert workloads.database_pod(_database_env(env_factory, "db.postgres.database.azure.com")) is None


def test_workload_ref_names_the_kind(env_factory):
    env = env_factory()
    env.__dict__["workloads"] = lambda: [{"kind": "StatefulSet", "metadata": {"name": "clamav"}}]
    assert workloads.workload_ref(env, "clamav") == "statefulset/clamav"
    assert workloads.workload_ref(env, "redis") is None
