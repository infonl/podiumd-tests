"""Unit tests for the preflight checks."""

from podiumd_tests import doctor
from podiumd_tests.environment import Environment


def which_all(tool):
    return f"/usr/bin/{tool}"


def statuses(checks):
    return {c.name: c.status for c in checks}


def test_missing_context_fails_and_skips_cluster_secrets(profile_factory, fake_runner, monkeypatch):
    fake_runner.answers["config get-contexts"] = (0, "other\n")
    profile = profile_factory(urls={}, secrets={"pw": {"k8s_secret": {"name": "s", "key": "k"}}})
    checks = doctor.run_checks(Environment(profile, fake_runner, environ={}), which=which_all)
    result = statuses(checks)
    assert result["kube context"] == "fail"
    assert result["secret pw"] == "skip"
    assert doctor.failed(checks)


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
