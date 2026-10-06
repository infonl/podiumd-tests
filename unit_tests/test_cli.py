"""Unit tests for the podiumd-tests command."""

import json

import pytest

from podiumd_tests import cli
from podiumd_tests.kube import Kube


@pytest.mark.parametrize(
    ("host", "component"),
    [
        ("contact.kees00.pd.test-rig.nl", "kiss"),
        ("ontw-mijn.dimpact.icatt.nl", "openinwoner"),
        ("test-openzaak.dimpact.nl", "openzaak"),
        ("openformulieren-nginx.local", "openformulieren"),
        ("apisix-admin.kees00.pd.test-rig.nl", None),
    ],
)
def test_component_for_host(host, component):
    assert cli.component_for_host(host) == component


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
