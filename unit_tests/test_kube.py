"""Unit tests for the kubectl wrapper."""

import json
import subprocess

import pytest

from podiumd_tests.kube import Kube
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import context_names
from podiumd_tests.kube import django_value


def test_every_command_has_context_and_namespace(fake_runner):
    fake_runner.answers["get pods"] = (0, json.dumps({"items": [{"metadata": {"name": "p1"}}]}))
    items = Kube("ctx", "ns", fake_runner).items("pods")
    assert fake_runner.calls[0][:5] == ["kubectl", "--context", "ctx", "--namespace", "ns"]
    assert items == [{"metadata": {"name": "p1"}}]


def test_all_namespaces_replaces_the_namespace(fake_runner):
    fake_runner.answers["get ingresses"] = (0, json.dumps({"items": []}))
    Kube("ctx", "ns", fake_runner).items("ingresses", all_namespaces=True)
    assert "--namespace" not in fake_runner.calls[0]
    assert fake_runner.calls[0][-1] == "--all-namespaces"


def test_errors_keep_the_command_and_the_last_stderr_line(fake_runner):
    fake_runner.answers["get --raw"] = (1, "E1005 noise\nE1005 noise\nUnable to connect to the server\n")
    with pytest.raises(KubeError) as info:
        Kube("ctx", "ns", fake_runner).api_reachable()
    assert str(info.value).endswith(": Unable to connect to the server")
    assert info.value.command.startswith("kubectl --context ctx")


def test_missing_kubectl_is_reported():
    def runner(args, timeout):
        raise FileNotFoundError(args[0])

    with pytest.raises(KubeError, match="kubectl not found on PATH"):
        Kube("ctx", "ns", runner).run("version")


def test_invalid_json_is_reported(fake_runner):
    fake_runner.answers["get pods"] = (0, "not json")
    with pytest.raises(KubeError, match="invalid JSON"):
        Kube("ctx", "ns", fake_runner).get_json("pods")


def test_context_names(fake_runner):
    fake_runner.answers["config get-contexts"] = (0, "minikube\npodiumd-kees00-aks\n")
    assert context_names(fake_runner) == ["minikube", "podiumd-kees00-aks"]


def test_django_value_picks_the_marked_line_from_django_chatter():
    output = "118 objects imported automatically (use -v 2 for details).\n\nPTEST_VALUE=s3cret=with=equals\n"
    assert django_value(output) == "s3cret=with=equals"


def test_django_value_without_marker_is_an_error():
    with pytest.raises(ValueError, match="no PTEST_VALUE= line"):
        django_value("118 objects imported automatically\nTraceback ...\n")


def test_context_names_timeout_is_a_kube_error():
    def runner(args, timeout):
        raise subprocess.TimeoutExpired(args, timeout)

    with pytest.raises(KubeError, match="timed out after 30s"):
        context_names(runner)


def test_invalid_json_error_shows_the_command_that_ran(fake_runner):
    fake_runner.answers["get pods"] = (0, "not json")
    with pytest.raises(KubeError) as info:
        Kube("ctx", "ns", fake_runner).get_json("pods", namespace="other")
    assert info.value.command == "kubectl --context ctx --namespace other get pods -o json"
