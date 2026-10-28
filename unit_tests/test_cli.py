"""Unit tests for the podiumd-tests command."""

import argparse
import json

from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

import pytest
import yaml

from podiumd_tests import cli
from podiumd_tests.bootstrap import Outcome
from podiumd_tests.capabilities import CLUSTER
from podiumd_tests.capabilities import Capabilities
from podiumd_tests.config import ProfileError
from podiumd_tests.doctor import Check
from podiumd_tests.kube import Kube
from podiumd_tests.lock import LockBusyError
from podiumd_tests.process import ProcessError
from podiumd_tests.sweep import Swept


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
        ("full", {}, "8"),
        ("full", {"pytest_workers": "2"}, "2"),
        ("full", {"pytest_workers": "1"}, None),
        ("smoke", {}, None),
    ],
)
def test_parallel_tiers_run_on_xdist_workers(tmp_path, profile_factory, monkeypatch, tier, settings, workers):
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 24)
    args = cli.build_parser().parse_args(["run", "--env", "x", "--tier", tier])
    selection = cli.pytest_selection(
        profile_factory(settings=settings), tier, "2610071230a3f1", tmp_path / "j.xml", args
    )
    found = selection[selection.index("-n") + 1] if "-n" in selection else None
    assert found == workers


@pytest.mark.parametrize(("cpus", "workers"), [(24, 8), (16, 8), (12, 6), (8, 4), (4, 2), (2, 1), (1, 1), (None, 1)])
def test_default_workers_are_half_the_cpus_at_most_eight(cpus, workers):
    assert cli.default_workers(cpus) == workers


def test_a_path_after_dashes_narrows_the_tier(tmp_path, profile_factory):
    args = argparse.Namespace(keep_data=False, pytest_args=["tests/integration/test_sso.py", "-k", "zac"])
    selection = cli.pytest_selection(profile_factory(), "full", "2610071230a3f1", tmp_path / "j.xml", args)
    assert not any(a.endswith(("tests/smoke", "tests/component", "tests/integration")) for a in selection)
    assert selection[-3:] == ["tests/integration/test_sso.py", "-k", "zac"]


def test_a_node_id_narrows_the_tier(tmp_path, profile_factory):
    node = "tests/integration/test_continuiteit.py::test_stopped_component_harms_no_other[zac]"
    args = argparse.Namespace(keep_data=False, pytest_args=[node])
    assert cli.pytest_selection(profile_factory(), "full", "2610071230a3f1", tmp_path / "j.xml", args)[-1] == node


@pytest.mark.parametrize(
    "node",
    [
        "tests/integration/test_continuiteit.py::test_does_not_exist",
        "tests/integration/test_continuiteit.py::test_without_open_zaak_the_apps_say_so@destructive",
    ],
)
def test_an_unknown_node_id_is_refused(tmp_path, profile_factory, node):
    args = argparse.Namespace(keep_data=False, pytest_args=[node])
    with pytest.raises(ProfileError, match=r"no such test: "):
        cli.pytest_selection(profile_factory(), "full", "2610071230a3f1", tmp_path / "j.xml", args)


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


PROFILE = (
    "estate: externals\nallowed_tiers: [{tiers}]\nkube: {{context: c, namespace: podiumd}}\nurls: {{}}\n"
    "secrets: {{a_password: {{k8s_secret: {{name: s, key: k}}}}}}\n"
)


@pytest.fixture
def envs(tmp_path):
    """Writes profile e.yaml with the given allowed tiers; returns the CLI's leading arguments."""

    def write(tiers="smoke, full, perf"):
        (tmp_path / "e.yaml").write_text(PROFILE.format(tiers=tiers), encoding="utf-8")
        return ["--envs-dir", str(tmp_path)]

    return write


@dataclass
class Offline:
    present: frozenset[str] = frozenset()
    checks: list[Check] = field(default_factory=lambda: [Check("kubectl", "ok")])
    locks: list[str] = field(default_factory=list[str])


@pytest.fixture
def offline(monkeypatch, env_factory):
    """Commands get an Environment on fake_runner with the given capabilities, and record the locks they take."""
    state = Offline()

    def environment(profile):
        env = env_factory(profile, environ={"PODIUMD_TESTS_SECRET_A_PASSWORD": "s3cr3t"})
        env.capabilities = Capabilities(state.present, {CLUSTER: "kubectl failed"})
        return env

    @contextmanager
    def held(_env, what):
        state.locks.append(what)
        yield

    monkeypatch.setattr(cli, "Environment", environment)
    monkeypatch.setattr(cli, "held", held)
    monkeypatch.setattr(cli.doctor, "run_checks", lambda _env: state.checks)
    return state


def test_env_init_writes_a_draft_and_names_the_unmapped_hosts(tmp_path, monkeypatch, fake_runner, capsys):
    routes = {"items": [{"spec": {"hostnames": ["ontw-zac.x.nl", "wiki.x.nl"]}}]}
    fake_runner.answers["get ingresses"] = (0, json.dumps({"items": []}))
    fake_runner.answers["get httproutes"] = (0, json.dumps(routes))
    monkeypatch.setattr(cli, "Kube", lambda context, namespace: Kube(context, namespace, fake_runner))
    argv = ["--envs-dir", str(tmp_path), "env", "init", "ontw", "--estate", "externals", "--context", "aks"]
    assert cli.main(argv) == cli.EXIT_OK
    written = yaml.safe_load((tmp_path / "externals" / "ontw.yaml").read_text(encoding="utf-8"))
    assert written["urls"] == {"zac": "https://ontw-zac.x.nl"}
    assert written["kube"] == {"context": "aks", "namespace": "podiumd"}
    assert "hosts not mapped to a component: wiki.x.nl" in capsys.readouterr().out
    assert cli.main(argv) == cli.EXIT_CONFIG
    assert "use --force to overwrite" in capsys.readouterr().err


def test_env_init_falls_back_to_configured_hosts_and_writes_minikube_profiles_at_the_top(
    tmp_path, monkeypatch, fake_runner
):
    fake_runner.answers["get ingresses"] = (0, json.dumps({"items": []}))
    fake_runner.answers["get httproutes"] = (0, json.dumps({"items": []}))
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": []}))
    fake_runner.answers["get configmaps"] = (0, json.dumps({"items": [{"data": {"u": "https://zac.mk.local"}}]}))
    monkeypatch.setattr(cli, "Kube", lambda context, namespace: Kube(context, namespace, fake_runner))
    argv = ["--envs-dir", str(tmp_path), "env", "init", "mk", "--estate", "minikube", "--context", "minikube"]
    assert cli.main([*argv, "--scheme", "http"]) == cli.EXIT_OK
    written = yaml.safe_load((tmp_path / "mk.yaml").read_text(encoding="utf-8"))
    assert written["urls"] == {"zac": "http://zac.mk.local"}


def test_doctor_writes_the_checks_as_json_and_fails_on_a_failed_check(envs, offline, tmp_path, capsys):
    offline.checks = [Check("kubectl", "ok"), Check("cluster", "fail", "no access", "az login")]
    target = tmp_path / "checks.json"
    assert cli.main([*envs(), "doctor", "--env", "e", "--json", str(target)]) == cli.EXIT_CONFIG
    assert json.loads(target.read_text(encoding="utf-8"))[1] == {
        "name": "cluster",
        "status": "fail",
        "detail": "no access",
        "hint": "az login",
    }
    assert "hint: az login" in capsys.readouterr().out


def test_bootstrap_refuses_a_smoke_only_environment(envs, offline, capsys):
    assert cli.main([*envs("smoke"), "bootstrap", "--env", "e"]) == cli.EXIT_NOT_ALLOWED
    assert "refused: e is smoke-only" in capsys.readouterr().err


def test_bootstrap_stops_on_a_failed_preflight_and_without_cluster_access(envs, offline, capsys):
    offline.checks = [Check("cluster", "fail", "no access")]
    assert cli.main([*envs(), "bootstrap", "--env", "e"]) == cli.EXIT_CONFIG
    assert "no access" in capsys.readouterr().err
    assert cli.main([*envs(), "unbootstrap", "--env", "e", "--skip-doctor"]) == cli.EXIT_CONFIG
    assert "bootstrap needs kubectl access to e: requires: cluster (kubectl failed)" in capsys.readouterr().err
    assert offline.locks == []


def test_bootstrap_runs_the_selected_steps_under_the_lock(envs, offline, monkeypatch, capsys):
    offline.present = frozenset({CLUSTER})
    calls = []

    def fake_bootstrap(_env, steps, *, rotate):
        calls.append(([s.name for s in steps], rotate))
        return [Outcome("openklant-token", "created")]

    monkeypatch.setattr(cli, "bootstrap", fake_bootstrap)
    argv = [*envs(), "bootstrap", "--env", "e", "--step", "openklant-token", "--rotate"]
    assert cli.main(argv) == cli.EXIT_OK
    assert calls == [(["openklant-token"], True)]
    assert offline.locks == ["bootstrap e"]
    assert "created  openklant-token" in capsys.readouterr().out


def test_unbootstrap_exits_with_config_code_when_a_step_fails(envs, offline, monkeypatch):
    offline.present = frozenset({CLUSTER})
    monkeypatch.setattr(cli, "unbootstrap", lambda _env, _steps: [Outcome("openklant-token", "failed", "403")])
    assert cli.main([*envs(), "unbootstrap", "--env", "e"]) == cli.EXIT_CONFIG
    assert offline.locks == ["unbootstrap e"]


def test_sweep_rejects_a_bad_age_and_a_smoke_only_environment(envs, offline, capsys):
    assert cli.main([*envs(), "sweep", "--env", "e", "--older-than", "soon"]) == cli.EXIT_CONFIG
    assert "--older-than:" in capsys.readouterr().err
    assert cli.main([*envs("smoke"), "sweep", "--env", "e"]) == cli.EXIT_NOT_ALLOWED
    offline.checks = [Check("cluster", "fail")]
    assert cli.main([*envs(), "sweep", "--env", "e"]) == cli.EXIT_CONFIG


def test_sweep_locks_only_when_it_deletes(envs, offline, monkeypatch, capsys):
    runs = []

    def fake_sweep(_env, _cutoff, *, dry_run):
        runs.append(dry_run)
        return [Swept("zaken", "z1", "found" if dry_run else "failed")]

    monkeypatch.setattr(cli, "sweep", fake_sweep)
    assert cli.main([*envs(), "sweep", "--env", "e", "--dry-run"]) == cli.EXIT_OK
    assert offline.locks == []
    assert cli.main([*envs(), "sweep", "--env", "e"]) == cli.EXIT_CONFIG
    assert offline.locks == ["sweep e"]
    assert runs == [True, False]
    assert "failed   zaken" in capsys.readouterr().out


def test_volume_commands_need_the_perf_tier(envs, offline, capsys):
    assert cli.main([*envs("smoke, full"), "seed-volume", "--env", "e"]) == cli.EXIT_NOT_ALLOWED
    assert "does not allow tier perf" in capsys.readouterr().err
    offline.checks = [Check("cluster", "fail")]
    assert cli.main([*envs(), "unseed-volume", "--env", "e"]) == cli.EXIT_CONFIG


def test_volume_commands_seed_and_unseed_under_the_lock(envs, offline, monkeypatch, capsys):
    scaled = []

    @contextmanager
    def faster(_env, replicas):
        scaled.append(replicas)
        yield

    monkeypatch.setattr(cli, "faster", faster)
    monkeypatch.setattr(cli, "seed", lambda _env, scale, parallel: {f"{scale}/{parallel}": 1})
    monkeypatch.setattr(cli, "unseed", lambda _env: {"unseeded": 2})
    monkeypatch.setattr(cli, "format_seeded", lambda counts: f"counts {counts}")
    argv = [*envs(), "seed-volume", "--env", "e", "--scale", "perf", "--parallel", "2", "--scale-cluster", "3"]
    assert cli.main(argv) == cli.EXIT_OK
    assert cli.main([*envs(), "unseed-volume", "--env", "e"]) == cli.EXIT_OK
    assert scaled == [3]
    assert offline.locks == ["seed-volume e", "unseed-volume e"]
    assert capsys.readouterr().out == "counts {'perf/2': 1}\ncounts {'unseeded': 2}\n"


def test_run_stops_on_a_failed_preflight(envs, offline, tmp_path, monkeypatch):
    offline.checks = [Check("cluster", "fail")]
    monkeypatch.setattr(cli.pytest, "main", lambda _args: pytest.fail("pytest must not run"))
    assert cli.main([*envs(), "run", "--env", "e", "--results-dir", str(tmp_path / "r")]) == cli.EXIT_CONFIG


JUNIT = (
    '<testsuites><testsuite name="pytest" tests="1" failures="1">'
    '<testcase classname="tests.smoke.test_a" name="test_a"><failure message="token s3cr3t">s3cr3t</failure>'
    "</testcase></testsuite></testsuites>"
)


@pytest.mark.parametrize(
    ("exit_code", "expected"),
    [
        (pytest.ExitCode.TESTS_FAILED, cli.EXIT_TESTS_FAILED),
        (pytest.ExitCode.NO_TESTS_COLLECTED, cli.EXIT_OK),
        (pytest.ExitCode.USAGE_ERROR, cli.EXIT_CONFIG),
    ],
)
def test_run_records_redacted_results_under_the_lock(envs, offline, tmp_path, monkeypatch, exit_code, expected):
    results = tmp_path / "r"
    offline.present = frozenset({CLUSTER})

    def fake_pytest(args):
        junit = Path(next(a for a in args if a.startswith("--junitxml=")).removeprefix("--junitxml="))
        junit.write_text(JUNIT, encoding="utf-8")
        return exit_code

    monkeypatch.setattr(cli.pytest, "main", fake_pytest)
    monkeypatch.setattr(cli, "publish_summary", lambda _summary: None)
    assert cli.main([*envs(), "run", "--env", "e", "--tier", "full", "--results-dir", str(results), "--", "-x"]) == (
        expected
    )
    assert offline.locks == ["run full e"]
    (run,) = results.glob("*/*/run.json")
    info = json.loads(run.read_text(encoding="utf-8"))
    assert info["selection"][-1] == "-x"
    assert info["versions"] == {}
    assert info["chart_version"] is None
    junit = (run.parent / "junit.xml").read_text(encoding="utf-8")
    assert "s3cr3t" not in junit


@pytest.mark.parametrize(
    ("error", "code", "prefix"),
    [
        (ProcessError(["kubectl"], "boom"), cli.EXIT_CONFIG, "error: "),
        (LockBusyError("held by podiumd-minikube"), cli.EXIT_BUSY, "busy: "),
    ],
)
def test_main_turns_process_and_lock_errors_into_exit_codes(envs, monkeypatch, capsys, error, code, prefix):
    def fail(_args):
        raise error

    monkeypatch.setattr(cli, "cmd_doctor", fail)
    assert cli.main([*envs(), "doctor", "--env", "e"]) == code
    assert capsys.readouterr().err.startswith(prefix)
