"""Unit tests for Cilium and Hubble detection."""

import json

from podiumd_tests import doctor
from podiumd_tests.capabilities import detect
from podiumd_tests.cilium import detect_network
from podiumd_tests.kube import Kube


def agent(name, *, ready=True):
    status = {"phase": "Running", "containerStatuses": [{"name": "cilium-agent", "ready": ready}]}
    return {"metadata": {"name": name}, "status": status}


def items(*found):
    return (0, json.dumps({"items": list(found)}))


def test_cilium_and_hubble_are_present_when_their_pods_and_relay_run(fake_runner):
    fake_runner.answers.update(
        {
            "get pods -l k8s-app=cilium": items(agent("cilium-a")),
            "get services": items({"metadata": {"name": "hubble-relay"}}),
        }
    )
    assert detect_network(Kube("ctx", "podiumd", fake_runner)) == (frozenset({"cilium", "hubble"}), {})


def test_a_cluster_without_cilium_says_why(fake_runner, profile_factory):
    fake_runner.answers.update({"get pods -l k8s-app=cilium": items(), "get services": items()})
    caps = detect(profile_factory(), [], detect_network(Kube("ctx", "podiumd", fake_runner)))
    assert caps.skip_reason("cilium") == "requires: cilium (no pods k8s-app=cilium in kube-system)"
    assert caps.skip_reason("hubble") == "requires: hubble (no Service hubble-relay in kube-system)"


def test_an_unreadable_kube_system_leaves_both_absent(fake_runner):
    present, reasons = detect_network(Kube("ctx", "podiumd", fake_runner))
    assert not present
    assert reasons["cilium"].startswith("cannot read namespace kube-system")


def test_without_cluster_the_network_is_unknown(profile_factory):
    assert detect(profile_factory(), None).reasons["cilium"] == "kube API not reachable"


def test_doctor_warns_about_an_unready_agent(fake_runner, env_factory, profile_factory):
    fake_runner.answers.update(
        {
            "config get-contexts": (0, "ctx\n"),
            "get --raw /readyz": (0, "ok"),
            "get namespace podiumd": (0, "namespace/podiumd"),
            "get deployments": items(),
            "get statefulsets": items(),
            "get pods -l k8s-app=cilium": items(agent("cilium-a"), agent("cilium-b", ready=False)),
            "get services": items(),
        }
    )
    checks = doctor.run_checks(env_factory(profile_factory(urls={})), which=lambda tool: f"/usr/bin/{tool}")
    cilium = next(c for c in checks if c.name == "cilium")
    assert (cilium.status, cilium.detail) == ("warn", "cilium-b/cilium-agent: not ready")
