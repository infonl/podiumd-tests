"""Unit tests for the preflight checks."""

import json
import socket
import subprocess
import time

from contextlib import contextmanager

import pytest
import requests

from podiumd_tests import doctor
from podiumd_tests.credentials import env_var_name
from podiumd_tests.kube import KubeError


def which_all(tool):
    return f"/usr/bin/{tool}"


def workload(kind, name, wanted, ready):
    return {"kind": kind, "metadata": {"name": name}, "spec": {"replicas": wanted}, "status": {"readyReplicas": ready}}


def statuses(checks):
    return {c.name: c.status for c in checks}


def test_missing_context_fails_in_host_header_mode(profile_factory, fake_runner, env_factory):
    fake_runner.answers["config get-contexts"] = (0, "other\n")
    access = {"mode": "host-header", "ingress_service": {"namespace": "traefik", "name": "traefik"}}
    profile = profile_factory(urls={}, access=access, secrets={"pw": {"k8s_secret": {"name": "s", "key": "k"}}})
    checks = doctor.run_checks(env_factory(profile), which=which_all)
    result = statuses(checks)
    assert result["kube context"] == "fail"
    assert result["secret pw"] == "skip"
    assert doctor.failed(checks)


def test_missing_context_only_warns_in_direct_mode(profile_factory, fake_runner, env_factory):
    fake_runner.answers["config get-contexts"] = (0, "other\n")
    checks = doctor.run_checks(env_factory(profile_factory(urls={})), which=which_all)
    result = statuses(checks)
    assert result["kube context"] == "warn"
    assert result["capabilities"] == "ok"
    assert not doctor.failed(checks)


def test_missing_kubectl_stops_early(env_factory):
    checks = doctor.run_checks(env_factory(), which=lambda tool: None)
    assert statuses(checks) == {"profile": "ok", "tool kubectl": "fail", "cluster": "skip"}


def test_healthy_cluster_without_urls(profile_factory, fake_runner, env_factory):
    fake_runner.answers.update(
        {
            "config get-contexts": (0, "ctx\n"),
            "get --raw /readyz": (0, "ok"),
            "get lease podiumd-tests-lock": (0, ""),
            "get namespace podiumd": (0, "namespace/podiumd"),
            "get deployments": (0, json.dumps({"items": [workload("Deployment", "openzaak", 1, 1)]})),
            "get statefulsets": (0, json.dumps({"items": [workload("StatefulSet", "redis", 2, 1)]})),
        }
    )
    checks = doctor.run_checks(env_factory(profile_factory(urls={}, allowed_tiers=["smoke", "core"])), which=which_all)
    result = statuses(checks)
    assert result["kube API"] == "ok"
    assert result["lock"] == "ok"
    assert result["workloads podiumd"] == "warn"
    assert "StatefulSet/redis 1/2" in next(c.detail for c in checks if c.name == "workloads podiumd")
    assert not doctor.failed(checks)


def test_smoke_only_profile_skips_the_lock(profile_factory, fake_runner, env_factory):
    fake_runner.answers.update({"config get-contexts": (0, "ctx\n"), "get --raw /readyz": (0, "ok")})
    checks = doctor.run_checks(env_factory(profile_factory(urls={})), which=which_all)
    assert statuses(checks)["lock"] == "skip"
    assert not any("lease" in call for call in fake_runner.calls)


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


def test_unresolvable_hosts_fail_without_http(profile_factory, fake_runner, env_factory):
    fake_runner.answers["config get-contexts"] = (0, "other\n")

    def resolve(_host):
        raise socket.gaierror(-2, "Name or service not known")

    profile = profile_factory(access={"mode": "direct"})
    checks = doctor.run_checks(env_factory(profile), which=which_all, resolve=resolve)
    result = statuses(checks)
    assert result["url openzaak"] == "fail"
    assert result["url keycloak-admin"] == "fail"
    assert all("DNS lookup failed" in c.detail for c in checks if c.name.startswith("url ")), checks


def test_checks_of_a_component_that_is_not_deployed_skip(profile_factory, fake_runner, env_factory):
    fake_runner.answers.update(
        {
            "config get-contexts": (0, "ctx\n"),
            "get --raw /readyz": (0, "ok"),
            "get namespace podiumd": (0, "namespace/podiumd"),
            "get deployments": (0, json.dumps({"items": [workload("Deployment", "openzaak", 1, 1)]})),
            "get statefulsets": (0, json.dumps({"items": []})),
        }
    )
    profile = profile_factory(
        urls={"omc": "https://omc.example.test"},
        secrets={"omc_jwt_secret": {"k8s_secret": {"name": "omc", "key": "k"}}},
    )
    result = statuses(doctor.run_checks(env_factory(profile), which=which_all, resolve=lambda _host: None))
    assert {result["url omc"], result["secret omc_jwt_secret"]} == {"skip"}


AKS = {"subscription": "sub", "resource_group": "rg", "name": "aks"}


def test_moved_aks_api_is_found_by_rewriting_the_context(profile_factory, fake_runner, env_factory):
    fake_runner.answers.update(
        {
            "config get-contexts": (0, "ctx\n"),
            "config current-context": (0, "other\n"),
            "az aks get-credentials": (0, ""),
            "config use-context other": (0, ""),
        }
    )
    fake_runner.answers["get --raw /readyz"] = (0, "ok")

    def runner(args, timeout, stdin=None):
        if "/readyz" in args and not any(c[:2] == ["az", "aks"] for c in fake_runner.calls):
            return subprocess.CompletedProcess(list(args), 1, "", "dial tcp: lookup old.azmk8s.io: no such host")
        return fake_runner(args, timeout, stdin)

    profile = profile_factory(urls={}, kube={"context": "ctx", "namespace": "podiumd", "aks": AKS})
    checks = doctor.run_checks(env_factory(profile, runner=runner), which=which_all)
    api = next(c for c in checks if c.name == "kube API")
    assert (api.status, api.detail) == ("ok", "readyz; context rewritten by az aks get-credentials")
    az = next(c for c in fake_runner.calls if c[:2] == ["az", "aks"])
    assert az[3:] == [
        "--subscription",
        "sub",
        "--resource-group",
        "rg",
        "--name",
        "aks",
        "--context",
        "ctx",
        "--overwrite-existing",
    ]
    assert ["kubectl", "config", "use-context", "other"] in fake_runner.calls


def test_unreachable_api_without_a_refresh_command_only_reports(profile_factory, fake_runner, env_factory):
    fake_runner.answers["config get-contexts"] = (0, "ctx\n")
    checks = doctor.run_checks(env_factory(profile_factory(urls={})), which=which_all)
    assert statuses(checks)["kube API"] == "warn"
    assert not any(c[0] in {"az", "minikube"} for c in fake_runner.calls)


def test_missing_minikube_context_is_rewritten_by_minikube(profile_factory, fake_runner, env_factory):
    fake_runner.answers.update(
        {"config get-contexts": (0, "other\n"), "minikube update-context": (0, ""), "get --raw /readyz": (0, "ok")}
    )
    profile = profile_factory(urls={}, estate="minikube", kube={"context": "minikube", "namespace": "podiumd"})
    checks = doctor.run_checks(env_factory(profile), which=which_all)
    assert statuses(checks)["kube context"] == "ok"
    assert ["minikube", "update-context", "--profile", "minikube"] in fake_runner.calls


HEALTHY = {
    "config get-contexts": (0, "ctx\n"),
    "get --raw /readyz": (0, "ok"),
    "get namespace podiumd": (0, "namespace/podiumd"),
    "get deployments": (0, json.dumps({"items": [workload("Deployment", "openzaak", 1, 1)]})),
    "get statefulsets": (0, json.dumps({"items": []})),
}


def test_unreadable_kubeconfig_fails(env_factory, fake_http):
    fake_http()
    checks = doctor.run_checks(env_factory(), which=which_all, resolve=lambda _host: None)
    assert statuses(checks)["kube context"] == "fail"


def test_failed_context_refresh_reports_the_missing_context(profile_factory, fake_runner, env_factory):
    fake_runner.answers["config get-contexts"] = (0, "other\n")
    profile = profile_factory(urls={}, estate="minikube", kube={"context": "minikube", "namespace": "podiumd"})
    checks = doctor.run_checks(env_factory(profile), which=which_all)
    context = next(c for c in checks if c.name == "kube context")
    assert (context.status, context.detail) == ("warn", "minikube not in kubeconfig")


@pytest.mark.parametrize(
    ("lease", "status", "detail"),
    [
        (None, "warn", "cannot read the lease"),
        (
            (0, json.dumps({"spec": {"holderIdentity": "kees", "acquireTime": "2999-01-01T00:00:00+00:00"}})),
            "warn",
            "held by kees since 2999-01-01 00:00Z",
        ),
    ],
    ids=["unreadable", "held"],
)
def test_lock_warns_when_held_or_unreadable(profile_factory, fake_runner, env_factory, lease, status, detail):
    fake_runner.answers.update(HEALTHY)
    if lease:
        fake_runner.answers["get lease podiumd-tests-lock"] = lease
    profile = profile_factory(urls={}, allowed_tiers=["smoke", "core"])
    lock = next(c for c in doctor.run_checks(env_factory(profile), which=which_all) if c.name == "lock")
    assert lock.status == status
    assert lock.detail.startswith(detail)


def test_url_checks_report_status_and_server_errors(profile_factory, fake_runner, env_factory, fake_http):
    fake_runner.answers.update(HEALTHY)
    urls = {"openzaak": "https://openzaak.example.test", "objecten": "https://objecten.example.test"}
    fake_http({"/": (200, {})})
    checks = doctor.run_checks(env_factory(profile_factory(urls=urls)), which=which_all, resolve=lambda _host: None)
    found = {c.name: (c.status, c.detail) for c in checks if c.name.startswith("url ")}
    assert found["url openzaak"] == ("ok", "https://openzaak.example.test: HTTP 200")
    assert found["url objecten"][0] == "skip"


OZ = "https://openzaak.example.test"
REFUSED = requests.exceptions.ConnectionError()


@pytest.mark.parametrize(
    ("answer", "status", "detail"),
    [
        (requests.exceptions.SSLError("bad cert"), "fail", f"{OZ}: TLS error: bad cert"),
        (requests.exceptions.ConnectTimeout(), "fail", f"{OZ}: no connection within {doctor.HTTP_TIMEOUT[0]}s"),
        (REFUSED, "fail", f"{OZ}: ConnectionError"),
        (502, "fail", f"{OZ}: HTTP 502"),
    ],
    ids=["tls", "timeout", "refused", "server-error"],
)
def test_url_check_names_the_failure(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    profile_factory, fake_runner, env_factory, monkeypatch, response_factory, answer, status, detail
):
    fake_runner.answers.update(HEALTHY)

    def get_root(*_args):
        if isinstance(answer, Exception):
            raise answer
        return response_factory(status=answer)

    monkeypatch.setattr(doctor, "get_root", get_root)
    env = env_factory(profile_factory(urls={"openzaak": OZ}))
    checks = doctor.run_checks(env, which=which_all, resolve=lambda _host: None)
    url = next(c for c in checks if c.name == "url openzaak")
    assert (url.status, url.detail) == (status, detail)


def test_missing_ingress_ip_fails_the_urls(profile_factory, fake_runner, env_factory):
    fake_runner.answers.update(HEALTHY)
    fake_runner.answers["get svc traefik"] = (0, "")
    access = {"mode": "host-header", "ingress_service": {"namespace": "traefik", "name": "traefik"}}
    checks = doctor.run_checks(env_factory(profile_factory(access=access)), which=which_all)
    ingress = next(c for c in checks if c.name == "ingress IP")
    assert (ingress.status, "minikube tunnel" in ingress.detail) == ("fail", True)


def test_failed_port_forward_fails_the_urls(profile_factory, fake_runner, env_factory, monkeypatch):
    fake_runner.answers.update(HEALTHY)
    env = env_factory(profile_factory())

    @contextmanager
    def console_urls():
        raise KubeError(["kubectl", "port-forward"], "no pods")
        yield {}

    monkeypatch.setattr(env, "console_urls", console_urls)
    assert statuses(doctor.run_checks(env, which=which_all))["port-forward"] == "fail"


def test_secrets_resolve_or_fail_with_the_cluster(profile_factory, fake_runner, env_factory):
    fake_runner.answers.update(HEALTHY)
    secrets = {"pw": {"k8s_secret": {"name": "s", "key": "k"}}, "gone": {"k8s_secret": {"name": "t", "key": "k"}}}
    env = env_factory(profile_factory(urls={}, secrets=secrets), environ={env_var_name("pw"): "s3cret"})
    checks = {c.name: c for c in doctor.run_checks(env, which=which_all)}
    assert (checks["secret pw"].status, checks["secret pw"].detail) == ("ok", "k8s_secret")
    assert checks["secret gone"].status == "fail"
