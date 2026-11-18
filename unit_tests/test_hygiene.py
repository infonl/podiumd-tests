"""Unit tests for the deployment hygiene checks."""

import json

from podiumd_tests.hygiene import baseline_violations
from podiumd_tests.hygiene import clock_offset
from podiumd_tests.hygiene import cluster_names
from podiumd_tests.hygiene import conformance
from podiumd_tests.hygiene import database_time_zone
from podiumd_tests.hygiene import hosting_scope
from podiumd_tests.hygiene import is_hosted_component
from podiumd_tests.hygiene import literal_secrets
from podiumd_tests.hygiene import missing_probes
from podiumd_tests.hygiene import missing_requests
from podiumd_tests.hygiene import standards_report
from podiumd_tests.hygiene import unpinned_images
from podiumd_tests.hygiene import without_disruption_budget
from podiumd_tests.kube import metadata_name

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


def replicated(name, replicas, labels, namespace="podiumd"):
    return {
        "metadata": {"name": name, "namespace": namespace},
        "spec": {"replicas": replicas, "template": {"metadata": {"labels": labels}}},
    }


def budget(match_labels, namespace="podiumd"):
    return {"metadata": {"namespace": namespace}, "spec": {"selector": {"matchLabels": match_labels}}}


def test_replicated_workloads_without_a_selecting_budget_are_named():
    workloads = [
        replicated("keycloak", 2, {"app": "keycloak", "tier": "web"}),
        replicated("solr", 3, {"app": "solr"}),
        replicated("single", 1, {"app": "single"}),
        replicated("elsewhere", 2, {"app": "elsewhere"}, namespace="other"),
    ]
    budgets = [budget({"app": "solr"}), budget({"app": "elsewhere"}), budget({"app": "keycloak", "tier": "db"})]
    assert without_disruption_budget(workloads, budgets) == ["keycloak", "elsewhere"]


def test_literal_secrets_name_credentials_set_by_value():
    env = [
        {"name": "DB_PASSWORD", "value": "s3cr3t"},
        {"name": "JWT_SECRET", "valueFrom": {"secretKeyRef": {"name": "s", "key": "k"}}},
        {"name": "API_KEY_FILE", "value": "/run/key"},
        {"name": "TOKEN_LIFETIME", "value": "3600"},
        {"name": "AUTH_TOKEN_ENABLED", "value": "true"},
        {"name": "ETCD_INITIAL_CLUSTER_TOKEN", "value": "etcd-cluster"},
        {"name": "OIDC_CLIENT_SECRET", "value": ""},
    ]
    found = literal_secrets(workload(containers=[{"name": "app", "image": "a:1", "env": env}]))
    assert found == ["w/app: DB_PASSWORD"]


def service(selector, target, namespace="podiumd"):
    return {
        "metadata": {"namespace": namespace},
        "spec": {"selector": selector, "ports": [{"port": 80, "targetPort": target}]},
    }


def probed_workload(containers):
    return {
        "metadata": {"name": "w", "namespace": "podiumd"},
        "spec": {"template": {"metadata": {"labels": {"app": "w"}}, "spec": {"containers": containers}}},
    }


def test_missing_probes_concern_only_containers_a_service_serves():
    probes = {"livenessProbe": {}, "readinessProbe": {}}
    containers = [
        {"name": "web", "ports": [{"containerPort": 8000}], "livenessProbe": {}},
        {"name": "nginx", "ports": [{"containerPort": 80, "name": "http"}], **probes},
        {"name": "exporter", "ports": [{"containerPort": 9121}]},
    ]
    services = [service({"app": "w"}, 8000), service({"app": "w"}, "http"), service({"app": "w"}, 9121, "other")]
    assert missing_probes(probed_workload(containers), services) == ["w/web: no readinessProbe"]


def test_conformance_reads_each_standard_and_the_report_counts_them():
    secure = {"runAsNonRoot": True, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}
    container = {
        "name": "app",
        "image": "a:1",
        "resources": {**REQUESTS, "limits": {"memory": "1Gi"}},
        "securityContext": secure,
        "startupProbe": {},
    }
    good = {
        "kind": "Deployment",
        "metadata": {"name": "good", "namespace": "podiumd"},
        "spec": {
            "replicas": 2,
            "template": {
                "metadata": {"labels": {"app": "good"}},
                "spec": {"containers": [container], "topologySpreadConstraints": [{}]},
            },
        },
    }
    plain = {**workload(), "kind": "StatefulSet"}
    objects = {
        "services": [],
        "budgets": [budget({"app": "good"})],
        "autoscalers": [{"spec": {"scaleTargetRef": {"name": "good"}}}],
    }
    assert all(conformance(good, objects).values())
    assert conformance(plain, objects) == {
        "secrets": True,
        "probes": True,
        "startup": False,
        "limits": False,
        "non-root": False,
        "drop ALL": False,
        "read-only fs": False,
        "2+ replicas": False,
        "PDB": False,
        "spread": False,
        "HPA": False,
    }
    report = standards_report([good, plain], objects, "Standards")
    assert "| limits | COMP020 | 1 / 2 |" in report
    assert "| StatefulSet w | yes | yes | **no** |" in report


def test_hosted_components_leave_out_stand_ins_and_operator_workloads():
    operated = {"metadata": {"name": "es", "ownerReferences": [{"kind": "Elasticsearch"}]}}
    assert [is_hosted_component(w) for w in (workload(), operated, {"metadata": {"name": "mailpit"}})] == [
        True,
        False,
        False,
    ]


def test_clock_offset_runs_date_in_the_first_container(env_factory, fake_runner):
    fake_runner.answers["exec sts/db -c main -- date +%z"] = (0, "+0100\n")
    fake_runner.answers["exec deploy/quiet"] = (1, "executable file not found")
    env = env_factory()
    db = {
        "kind": "StatefulSet",
        "metadata": {"name": "db"},
        "spec": {"template": {"spec": {"containers": [{"name": "main"}]}}},
    }
    quiet = {**db, "kind": "Deployment", "metadata": {"name": "quiet"}}
    assert [clock_offset(env, w) for w in (db, quiet, {**db, "kind": "Job"})] == ["+0100", None, None]


def test_database_time_zone_reads_the_reset_value(env_factory, fake_runner):
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "openzaak"}}]}))
    fake_runner.answers["exec -i deploy/openzaak"] = (0, "12 objects imported\nPTEST_VALUE=Etc/UTC\n")
    assert database_time_zone(env_factory()) == "Etc/UTC"
    assert "reset_val" in str(fake_runner.stdins[-1])


def test_hosting_scope_reads_workloads_and_their_objects(env_factory, fake_runner):
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "a"}}]}))
    for kind in ("statefulsets", "services", "poddisruptionbudgets", "horizontalpodautoscalers"):
        fake_runner.answers[f"get {kind}"] = (0, json.dumps({"items": []}))
    workloads, objects = hosting_scope(env_factory(), ["podiumd"])
    assert ([metadata_name(w) for w in workloads], sorted(objects)) == (
        ["a"],
        ["autoscalers", "budgets", "services"],
    )


def test_cluster_names_are_the_services_three_dns_names(env_factory, fake_runner):
    deployment = {**probed_workload([]), "metadata": {"name": "openzaak", "namespace": "podiumd"}}
    ports = [{"name": "metrics", "port": 9090}, {"name": "http", "port": 80}]
    zaak = {
        "metadata": {"name": "openzaak", "namespace": "podiumd"},
        "spec": {"selector": {"app": "w"}, "ports": ports},
    }
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [deployment]}))
    fake_runner.answers["get services"] = (0, json.dumps({"items": [zaak]}))
    assert cluster_names(env_factory(), "openzaak") == [
        "http://openzaak:80/",
        "http://openzaak.podiumd:80/",
        "http://openzaak.podiumd.svc.cluster.local:80/",
    ]
    assert cluster_names(env_factory(), "keycloak") == []
