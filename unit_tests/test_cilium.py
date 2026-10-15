"""Unit tests for Cilium and Hubble detection."""

import json

from podiumd_tests import doctor
from podiumd_tests.capabilities import detect
from podiumd_tests.cilium import describe_drops
from podiumd_tests.cilium import detect_network
from podiumd_tests.cilium import policy_drop
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


def drop(reason, src="10.0.0.1", dst="10.0.0.2", port="7800"):
    summary = {"l3": {"src": src, "dst": dst}, "l4": {"src": "38500", "dst": port}}
    return {"type": "drop", "reason": reason, "summary": summary}


def test_onlypolicy_drops_are_kept():
    assert policy_drop(json.dumps(drop("Policy denied"))) == drop("Policy denied")
    assert policy_drop(json.dumps(drop("Unsupported L3 protocol"))) is None
    assert policy_drop('time=2026-10-15T13:19:42Z level=info msg="Initializing dissection cache..."') is None


def test_drops_name_the_pods_and_count_retries(tmp_path, fake_runner):
    pod = {"metadata": {"name": "openzaak-1", "namespace": "podiumd"}, "status": {"podIP": "10.0.0.1"}}
    fake_runner.answers["get pods -o json --all-namespaces"] = items(pod)
    path = tmp_path / "cilium-drops.jsonl"
    lines = [{"time": f"t{i}", **drop("Policy denied")} for i in range(3)]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    assert describe_drops(Kube("ctx", "podiumd", fake_runner), path) == [
        "t0 podiumd/openzaak-1 -> 10.0.0.2:7800 Policy denied (3x)"
    ]


def test_no_recording_means_no_drops(tmp_path, fake_runner):
    assert describe_drops(Kube("ctx", "podiumd", fake_runner), tmp_path / "absent.jsonl") == []
