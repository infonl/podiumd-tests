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
    def runner(args, timeout, _stdin=None):
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
    def runner(args, timeout, _stdin=None):
        raise subprocess.TimeoutExpired(args, timeout)

    with pytest.raises(KubeError, match="timed out after 30s"):
        context_names(runner)


def test_invalid_json_error_shows_the_command_that_ran(fake_runner):
    fake_runner.answers["get pods"] = (0, "not json")
    with pytest.raises(KubeError) as info:
        Kube("ctx", "ns", fake_runner).get_json("pods", namespace="other")
    assert info.value.command == "kubectl --context ctx --namespace other get pods -o json"


def test_apply_sends_the_manifest_on_stdin(fake_runner):
    fake_runner.answers["apply -f -"] = (0, "secret/x configured")
    Kube("ctx", "ns", fake_runner).apply({"kind": "Secret", "stringData": {"k": "s3cret"}})
    assert "s3cret" not in " ".join(fake_runner.calls[0])
    assert '"s3cret"' in fake_runner.stdins[0]


def test_exec_errors_show_the_programs_error_not_the_exit_code_line(fake_runner):
    fake_runner.answers["exec -i deploy/openzaak"] = (
        1,
        "Traceback (most recent call last):\n  ...\ndjango.core.exceptions.FieldError: bad lookup\ncommand terminated with exit code 1\n",
    )
    with pytest.raises(KubeError, match=r"FieldError: bad lookup$"):
        Kube("ctx", "ns", fake_runner).exec_django_shell("openzaak", "print(1)")


def test_exec_errors_prefer_the_exception_over_later_log_lines(fake_runner):
    stderr = [
        "Traceback (most recent call last):",
        "django.db.utils.IntegrityError: duplicate key",
        '{"event": "serializer warning", "level": "warning"}',
        "command terminated with exit code 1",
    ]
    fake_runner.answers["exec -i deploy/openzaak"] = (1, "\n".join(stderr))
    with pytest.raises(KubeError, match=r"IntegrityError: duplicate key$"):
        Kube("ctx", "ns", fake_runner).exec_django_shell("openzaak", "print(1)")


def test_logs_reads_a_deployments_recent_lines_of_one_container(fake_runner):
    fake_runner.answers["logs deployment/zac"] = (0, "line 1\nline 2\n")
    assert Kube("ctx", "podiumd", fake_runner).logs("zac", since="10m", container="zac") == "line 1\nline 2\n"
    assert fake_runner.calls[-1][-3:] == ["deployment/zac", "--since=10m", "--container=zac"]
