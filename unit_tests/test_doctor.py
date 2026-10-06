"""Unit tests for the preflight checks."""

import socket
import time

from podiumd_tests import doctor
from podiumd_tests.environment import Environment


def which_all(tool):
    return f"/usr/bin/{tool}"


def statuses(checks):
    return {c.name: c.status for c in checks}


def test_missing_context_fails_in_host_header_mode(profile_factory, fake_runner):
    fake_runner.answers["config get-contexts"] = (0, "other\n")
    access = {"mode": "host-header", "ingress_service": {"namespace": "traefik", "name": "traefik"}}
    profile = profile_factory(urls={}, access=access, secrets={"pw": {"k8s_secret": {"name": "s", "key": "k"}}})
    checks = doctor.run_checks(Environment(profile, fake_runner, environ={}), which=which_all)
    result = statuses(checks)
    assert result["kube context"] == "fail"
    assert result["secret pw"] == "skip"
    assert doctor.failed(checks)


def test_missing_context_only_warns_in_direct_mode(profile_factory, fake_runner):
    fake_runner.answers["config get-contexts"] = (0, "other\n")
    checks = doctor.run_checks(Environment(profile_factory(urls={}), fake_runner, environ={}), which=which_all)
    result = statuses(checks)
    assert result["kube context"] == "warn"
    assert result["capabilities"] == "ok"
    assert not doctor.failed(checks)


def test_missing_kubectl_stops_early(profile_factory, fake_runner):
    checks = doctor.run_checks(Environment(profile_factory(), fake_runner, environ={}), which=lambda tool: None)
    assert statuses(checks) == {"profile": "ok", "tool kubectl": "fail", "cluster": "skip"}


def test_healthy_cluster_without_urls(profile_factory, fake_runner):
    fake_runner.answers.update(
        {
            "config get-contexts": (0, "ctx\n"),
            "get --raw /readyz": (0, "ok"),
            "get namespace podiumd": (0, "namespace/podiumd"),
            "get deployments": (
                0,
                '{"items": [{"metadata": {"name": "openzaak"}, "spec": {"replicas": 2}, "status": {"readyReplicas": 1}}]}',
            ),
        }
    )
    checks = doctor.run_checks(Environment(profile_factory(urls={}), fake_runner, environ={}), which=which_all)
    result = statuses(checks)
    assert result["kube API"] == "ok"
    assert result["deployments podiumd"] == "warn"
    assert not doctor.failed(checks)


def test_format_shows_hints_for_failures_only():
    text = doctor.format_checks(
        [
            doctor.Check("kube API", "fail", "unreachable", "cluster stopped?"),
            doctor.Check("profile", "ok", "envs/x.yaml", "unused hint"),
        ]
    )
    assert "hint: cluster stopped?" in text
    assert "unused hint" not in text


def test_resolve_hosts_stops_waiting_at_the_deadline():
    def resolve(host):
        if host == "slow.test":
            time.sleep(2)
        elif host == "unknown.test":
            raise socket.gaierror(-2, "Name or service not known")

    start = time.monotonic()
    result = doctor.resolve_hosts(["ok.test", "unknown.test", "slow.test"], resolve, timeout=0.2)
    assert time.monotonic() - start < 1
    assert result["ok.test"] == ""
    assert "Name or service not known" in result["unknown.test"]
    assert "no answer within 0.2s" in result["slow.test"]


def test_unresolvable_hosts_fail_without_http(profile_factory, fake_runner):
    fake_runner.answers["config get-contexts"] = (0, "other\n")

    def resolve(_host):
        raise socket.gaierror(-2, "Name or service not known")

    profile = profile_factory(access={"mode": "direct"})
    checks = doctor.run_checks(Environment(profile, fake_runner, environ={}), which=which_all, resolve=resolve)
    result = statuses(checks)
    assert result["url openzaak"] == "fail"
    assert result["url keycloak-admin"] == "fail"
    assert all("DNS lookup failed" in c.detail for c in checks if c.name.startswith("url ")), checks
