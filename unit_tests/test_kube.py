"""Unit tests for the kubectl wrapper."""

import io
import json
import pickle
import subprocess
import threading

from types import SimpleNamespace
from typing import cast

import pytest

from podiumd_tests import kube as kube_module
from podiumd_tests.kube import Kube
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import cluster_service
from podiumd_tests.kube import context_names
from podiumd_tests.kube import django_values
from podiumd_tests.kube import forwarded_port


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


def test_a_kube_error_survives_pickling():
    error = KubeError(["kubectl", "get", "pods"], "E1005 noise\nforbidden\n")
    copy = pickle.loads(pickle.dumps(error))  # noqa: S301  # data pickled by this test
    assert (type(copy), str(copy), copy.command) == (KubeError, str(error), error.command)


def test_missing_kubectl_is_reported():
    def runner(args, _timeout, _stdin=None):
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


def test_django_values_picks_the_marked_lines_from_django_chatter():
    output = (
        "118 objects imported automatically (use -v 2 for details).\n\nPTEST_VALUE=s3cret=with=equals\nPTEST_VALUE=2\n"
    )
    assert django_values(output) == ["s3cret=with=equals", "2"]


def test_django_values_without_marker_is_an_error():
    with pytest.raises(ValueError, match="no PTEST_VALUE= line"):
        django_values("118 objects imported automatically\nTraceback ...\n")


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


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://frankgateway-outway.podiumd.svc.cluster.local:9080", ("frankgateway-outway", "podiumd", 9080)),
        ("http://outway.podiumd.svc", ("outway", "podiumd", 80)),
        ("https://outway.podiumd.svc.cluster.local", None),
        ("https://zac.local", None),
    ],
)
def test_cluster_service_only_for_http_on_a_service_name(url, expected):
    assert cluster_service(url) == expected


def fake_process(output):
    return cast("subprocess.Popen[str]", SimpleNamespace(stdout=io.StringIO(output)))


def test_forwarded_port_is_read_from_kubectl_output():
    process = fake_process("Forwarding from 127.0.0.1:41235 -> 9080\nHandling connection\n")
    assert forwarded_port(["kubectl"], process, 5) == 41235


def test_forwarded_port_fails_with_kubectl_error_when_it_exits():
    process = fake_process('error: services "outway" not found\n')
    with pytest.raises(KubeError, match='services "outway" not found'):
        forwarded_port(["kubectl"], process, 5)


class SilentOutput:
    """Output of a kubectl that prints nothing until closed."""

    def __init__(self):
        self.closed: threading.Event = threading.Event()

    def __iter__(self):
        return self

    def __next__(self):
        self.closed.wait()
        raise StopIteration


@pytest.fixture
def silent_output():
    output = SilentOutput()
    yield output
    output.closed.set()


def test_forwarded_port_fails_when_kubectl_reports_nothing_in_time(silent_output):
    process = cast("subprocess.Popen[str]", SimpleNamespace(stdout=silent_output))
    with pytest.raises(KubeError, match=r"no forwarded port within 0\.05s"):
        forwarded_port(["kubectl"], process, 0.05)  # pyright: ignore[reportArgumentType]


def test_get_json_without_output_is_an_error_get_optional_is_none(fake_runner):
    fake_runner.answers["get secret"] = (0, "")
    kube = Kube("ctx", "ns", fake_runner)
    with pytest.raises(KubeError, match="empty output"):
        kube.get_json("secret", "s1")
    assert kube.get_optional("secret", "s1") is None


def test_get_json_of_a_json_list_is_an_error(fake_runner):
    fake_runner.answers["get pods"] = (0, "[]")
    with pytest.raises(KubeError, match="expected a JSON object"):
        Kube("ctx", "ns", fake_runner).get_json("pods")


def test_secret_value_decodes_one_key_and_names_a_missing_one(fake_runner):
    fake_runner.answers["get secret s1"] = (0, json.dumps({"data": {"password": "cHc="}}))
    kube = Kube("ctx", "ns", fake_runner)
    assert kube.secret_value("s1", "password") == "pw"
    with pytest.raises(KubeError, match="no key 'token'"):
        kube.secret_value("s1", "token")


class FakePortForward:
    """A `kubectl port-forward` process: stdout holds its output; records terminate and wait."""

    def __init__(self, output):
        self.stdout: io.StringIO = io.StringIO(output)
        self.stopped: list[str] = []

    def terminate(self):
        self.stopped.append("terminate")

    def wait(self, _timeout):
        self.stopped.append("wait")


def test_port_forward_yields_the_local_port_and_stops_kubectl(fake_runner, monkeypatch):
    process = FakePortForward("Forwarding from 127.0.0.1:41235 -> 80\n")
    started = []
    monkeypatch.setattr(kube_module, "start_process", lambda args: started.append(args) or process)
    with Kube("ctx", "ns", fake_runner).port_forward("outway", 80) as port:
        assert port == 41235
        assert process.stopped == []
    assert "service/outway" in started[0]
    assert process.stopped == ["terminate", "wait"]


def test_port_forward_without_kubectl_is_reported(fake_runner, monkeypatch):
    def missing(args):
        raise FileNotFoundError(args[0])

    monkeypatch.setattr(kube_module, "start_process", missing)
    kube = Kube("ctx", "ns", fake_runner)
    with pytest.raises(KubeError, match="kubectl not found on PATH"), kube.port_forward("outway", 80):
        pytest.fail("no port without kubectl")


def test_deploy_applies_restarts_and_waits_and_delete_all_goes_last_first(fake_runner):
    fake_runner.answers["kubectl"] = (0, "")
    kube = Kube("ctx", "ns", fake_runner)
    manifests: list[dict[str, object]] = [
        {"kind": "ConfigMap", "metadata": {"name": "c"}},
        {"kind": "Deployment", "metadata": {"name": "d"}},
    ]
    kube.deploy(manifests, "d", 60, restart=True)
    verbs = [" ".join(call[call.index("ns") + 1 : call.index("ns") + 3]) for call in fake_runner.calls]
    assert verbs == ["apply -f", "apply -f", "rollout restart", "rollout status"]
    fake_runner.calls.clear()
    kube.delete_all(manifests)
    assert [call[-2] for call in fake_runner.calls] == ["d", "c"]


def test_refresh_context_restores_the_current_context_under_its_lock(fake_runner, tmp_path, monkeypatch):
    monkeypatch.setattr(kube_module, "REFRESH_LOCK", tmp_path / "refresh.lock")
    fake_runner.answers = {"current-context": (0, "minikube\n"), "": (0, "")}
    kube_module.refresh_context(["az", "aks", "get-credentials"], fake_runner)
    assert fake_runner.calls[1:] == [["az", "aks", "get-credentials"], ["kubectl", "config", "use-context", "minikube"]]
    assert (tmp_path / "refresh.lock").exists()
