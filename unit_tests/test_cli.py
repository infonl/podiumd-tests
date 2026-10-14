"""Unit tests for the podiumd-tests command."""

import argparse
import json

import pytest

from podiumd_tests import cli
from podiumd_tests.config import ProfileError
from podiumd_tests.kube import Kube


def test_draft_profile_keeps_the_first_host_per_component_and_smoke_only():
    draft = cli.draft_profile(
        "externals", "aks-blue-ontw-icat", "podiumd", ["ontw-contact.x.nl", "ontw-kiss.x.nl", "ontw-zac.x.nl"], "https"
    )
    assert draft["urls"] == {"kiss": "https://ontw-contact.x.nl", "zac": "https://ontw-zac.x.nl"}
    assert draft["allowed_tiers"] == ["smoke"]


def test_run_refuses_a_tier_the_profile_does_not_allow(tmp_path, capsys):
    (tmp_path / "e.yaml").write_text(
        "estate: externals\nallowed_tiers: [smoke]\nkube: {context: c, namespace: podiumd}\nurls: {}\n"
    )
    code = cli.main(["--envs-dir", str(tmp_path), "run", "--env", "e", "--tier", "full"])
    assert code == cli.EXIT_NOT_ALLOWED
    assert "not allowed for e" in capsys.readouterr().err


def test_profile_errors_exit_with_config_code(tmp_path, capsys):
    code = cli.main(["--envs-dir", str(tmp_path), "doctor", "--env", "missing"])
    assert code == cli.EXIT_CONFIG
    assert "profile error" in capsys.readouterr().err


def test_env_list(capsys):
    assert cli.main(["env", "list"]) == cli.EXIT_OK
    assert "minikube" in capsys.readouterr().out


def test_ingress_hosts_from_ingress_rules_and_httproute_hostnames(fake_runner):
    ingresses = {"items": [{"spec": {"rules": [{"host": "zac.example.test"}, {"http": {}}]}}, {"spec": None}]}
    routes = {"items": [{"spec": {"hostnames": ["mijn.example.test", "zac.example.test"]}}]}
    fake_runner.answers["get ingresses"] = (0, json.dumps(ingresses))
    fake_runner.answers["get httproutes"] = (0, json.dumps(routes))
    assert cli.ingress_hosts(Kube("ctx", "ns", fake_runner)) == ["mijn.example.test", "zac.example.test"]


def test_ingress_hosts_skip_a_missing_gateway_api(fake_runner, capsys):
    fake_runner.answers["get ingresses"] = (0, json.dumps({"items": [{"spec": {"rules": [{"host": "zac.local"}]}}]}))
    fake_runner.answers["get httproutes"] = (1, 'error: the server doesn\'t have a resource type "httproutes"')
    assert cli.ingress_hosts(Kube("ctx", "ns", fake_runner)) == ["zac.local"]
    assert "skipping httproutes" in capsys.readouterr().err


def test_configured_hosts_from_deployments_and_config_maps(fake_runner):
    env = [{"name": "ALLOWED_HOSTS", "value": "openzaak.podiumd"}, {"name": "URL", "value": "https://test-zac.x.nl/"}]
    deployments = {"items": [{"spec": {"template": {"spec": {"containers": [{"env": env}]}}}}]}
    config_maps = {
        "items": [{"data": {"a": "http://openzaak.podiumd.svc.cluster.local", "b": "https://test-mijn.x.nl"}}]
    }
    fake_runner.answers["get deployments"] = (0, json.dumps(deployments))
    fake_runner.answers["get configmaps"] = (0, json.dumps(config_maps))
    assert cli.configured_hosts(Kube("ctx", "ns", fake_runner)) == ["test-mijn.x.nl", "test-zac.x.nl"]


def test_unknown_bootstrap_step_is_a_profile_error():
    with pytest.raises(ProfileError, match="unknown bootstrap steps: nope"):
        cli.selected_steps(["nope"])
    assert [s.name for s in cli.selected_steps(["openklant-token"])] == ["openklant-token"]


def test_run_keeps_screenshots_of_failed_browser_tests_but_no_traces(tmp_path, profile_factory):
    args = argparse.Namespace(keep_data=False, pytest_args=[])
    selection = cli.pytest_selection(profile_factory(), "smoke", "2610071230a3f1", tmp_path / "junit.xml", args)
    assert f"--output={tmp_path / 'artifacts'}" in selection
    assert "--screenshot=only-on-failure" in selection
    assert not any(a.startswith("--tracing") for a in selection)
    assert f"--html={tmp_path / 'report.html'}" in selection


@pytest.mark.parametrize(
    ("tier", "settings", "workers"),
    [
        ("full", {}, "4"),
        ("full", {"pytest_workers": "2"}, "2"),
        ("full", {"pytest_workers": "1"}, None),
        ("smoke", {}, None),
    ],
)
def test_parallel_tiers_run_on_xdist_workers(tmp_path, profile_factory, tier, settings, workers):
    args = cli.build_parser().parse_args(["run", "--env", "x", "--tier", tier])
    selection = cli.pytest_selection(
        profile_factory(settings=settings), tier, "2610071230a3f1", tmp_path / "j.xml", args
    )
    found = selection[selection.index("-n") + 1] if "-n" in selection else None
    assert found == workers


def test_a_path_after_dashes_narrows_the_tier(tmp_path, profile_factory):
    args = argparse.Namespace(keep_data=False, pytest_args=["tests/integration/test_sso.py", "-k", "zac"])
    selection = cli.pytest_selection(profile_factory(), "full", "2610071230a3f1", tmp_path / "j.xml", args)
    assert not any(a.endswith(("tests/smoke", "tests/component", "tests/integration")) for a in selection)
    assert selection[-3:] == ["tests/integration/test_sso.py", "-k", "zac"]


def test_a_path_outside_the_tier_is_refused(tmp_path, profile_factory):
    args = argparse.Namespace(keep_data=False, pytest_args=["tests/integration/test_sso.py"])
    with pytest.raises(ProfileError, match=r"not in tier smoke: tests/integration/test_sso\.py"):
        cli.pytest_selection(profile_factory(), "smoke", "2610071230a3f1", tmp_path / "j.xml", args)


def test_env_show_lists_where_each_secret_comes_from_but_no_value(tmp_path, capsys):
    (tmp_path / "x.yaml").write_text(
        "estate: minikube\nallowed_tiers: [smoke]\nkube: {context: minikube, namespace: podiumd}\nurls: {openzaak: https://openzaak.local}\n"
        "secrets:\n  a_password: {k8s_secret: {name: s, key: k}}\n  b_password: {dev_default: hunter2}\n",
        encoding="utf-8",
    )
    assert cli.main(["--envs-dir", str(tmp_path), "env", "show", "x"]) == 0
    out = capsys.readouterr().out
    assert "a_password                   k8s_secret key=k name=s\n" in out
    assert "b_password                   dev_default\n" in out
    assert "hunter2" not in out
