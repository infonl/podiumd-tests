"""Thin typed wrapper around the kubectl CLI.

Every call passes --context and --namespace explicitly, so the current
kubectl context never matters. The command line is kept in errors, so a
failing call can be pasted into a terminal and rerun.
"""

from __future__ import annotations

import base64
import json
import queue
import re
import threading
import time

from contextlib import contextmanager
from typing import TYPE_CHECKING
from typing import cast
from urllib.parse import urlsplit

from podiumd_tests.json_data import section
from podiumd_tests.process import ProcessError
from podiumd_tests.process import Runner
from podiumd_tests.process import run_checked
from podiumd_tests.process import run_process
from podiumd_tests.process import start_process

if TYPE_CHECKING:
    import subprocess  # nosec B404  # type only

    from collections.abc import Generator
    from collections.abc import Mapping
    from collections.abc import Sequence

DEFAULT_TIMEOUT = 30
# Django project path in every Maykin image (Open Zaak, Open Klant, Objecten, Open Inwoner).
MANAGE_PY = "/app/src/manage.py"
READ_STDIN = "import sys; exec(sys.stdin.read())"
DJANGO_VALUE_MARKER = "PTEST_VALUE="
SERVICE_HOST = re.compile(r"^(?P<service>[a-z0-9-]+)\.(?P<namespace>[a-z0-9-]+)\.svc(\.cluster\.local)?$")
FORWARDING = re.compile(r"^Forwarding from 127\.0\.0\.1:(\d+) -> \d+$")


class KubeError(ProcessError):
    """kubectl failed or returned something unexpected."""


class Kube:
    """kubectl bound to one context and default namespace."""

    def __init__(self, context: str, namespace: str, runner: Runner = run_process) -> None:
        self.context = context
        self.namespace = namespace
        self.runner = runner

    def command(self, *args: str, namespace: str | None = None, all_namespaces: bool = False) -> list[str]:
        """Full kubectl argv for the given arguments."""
        if all_namespaces:
            return ["kubectl", "--context", self.context, *args, "--all-namespaces"]
        ns = namespace if namespace is not None else self.namespace
        return ["kubectl", "--context", self.context, "--namespace", ns, *args]

    def run(
        self,
        *args: str,
        namespace: str | None = None,
        all_namespaces: bool = False,
        timeout: int = DEFAULT_TIMEOUT,
        stdin: str | None = None,
    ) -> str:
        """Run kubectl and return stdout; KubeError on failure."""
        command = self.command(*args, namespace=namespace, all_namespaces=all_namespaces)
        return run_checked(self.runner, command, timeout, KubeError, stdin)

    def apply(self, manifest: dict[str, object]) -> str:
        """`kubectl apply` a manifest given on stdin, so its values never appear in argv or errors."""
        return self.run("apply", "-f", "-", stdin=json.dumps(manifest))

    def delete(self, kind: str, name: str) -> str:
        """Delete an object; no error when it does not exist."""
        return self.run("delete", kind, name, "--ignore-not-found")

    def get_json(self, *args: str, namespace: str | None = None, all_namespaces: bool = False) -> dict[str, object]:
        """`kubectl get ... -o json` as a dict."""
        args = ("get", *args, "-o", "json")
        found = self._get_object(args, namespace, all_namespaces=all_namespaces)
        if found is None:
            raise KubeError(self.command(*args, namespace=namespace, all_namespaces=all_namespaces), "empty output")
        return found

    def get_optional(self, kind: str, name: str, *, namespace: str | None = None) -> dict[str, object] | None:
        """One object as a dict, or None when it does not exist."""
        return self._get_object(("get", kind, name, "--ignore-not-found", "-o", "json"), namespace)

    def _get_object(
        self, args: tuple[str, ...], namespace: str | None, *, all_namespaces: bool = False
    ) -> dict[str, object] | None:
        out = self.run(*args, namespace=namespace, all_namespaces=all_namespaces)
        if not out.strip():
            return None
        command = self.command(*args, namespace=namespace, all_namespaces=all_namespaces)
        try:
            data: object = json.loads(out)
        except json.JSONDecodeError as exc:
            raise KubeError(command, f"invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise KubeError(command, "expected a JSON object")
        return cast("dict[str, object]", data)

    def items(
        self, kind: str, *, namespace: str | None = None, all_namespaces: bool = False
    ) -> list[dict[str, object]]:
        """The items of a `kubectl get <kind>` list."""
        items = self.get_json(kind, namespace=namespace, all_namespaces=all_namespaces).get("items", [])
        return cast("list[dict[str, object]]", items) if isinstance(items, list) else []

    def api_reachable(self, timeout: int = 10) -> None:
        """Raise KubeError unless the API server answers /readyz."""
        self.run("get", "--raw", "/readyz", f"--request-timeout={timeout}s", timeout=timeout + 5)

    def logs(self, deployment: str, *, since: str, container: str | None = None) -> str:
        """The log lines a deployment's pod wrote in the last `since` (e.g. "5m")."""
        args = ["logs", f"deployment/{deployment}", f"--since={since}"]
        return self.run(*args, *([f"--container={container}"] if container else []))

    def exec(self, deployment: str, *argv: str, timeout: int = DEFAULT_TIMEOUT) -> str:
        """Run a command in the first pod of a deployment; return its stdout."""
        return self.run("exec", f"deploy/{deployment}", "--", *argv, timeout=timeout)

    def exec_django_shell(self, deployment: str, code: str, timeout: int = 60) -> str:
        """Run Python code in `manage.py shell` of a Django deployment; return its stdout.

        The code goes over stdin, so nothing in it appears in argv or errors.
        The stdout also holds Django's own chatter ("118 objects imported
        automatically"); use django_value() to pick out one printed value.
        `shell -c` reads stdin itself: plain `shell` checks stdin without
        waiting and falls back to the interactive interpreter when the code
        has not arrived yet.
        """
        return self.run(
            "exec",
            "-i",
            f"deploy/{deployment}",
            "--",
            "python",
            MANAGE_PY,
            "shell",
            "-c",
            READ_STDIN,
            stdin=code,
            timeout=timeout,
        )

    @contextmanager
    def port_forward(
        self, service: str, port: int, *, namespace: str | None = None, timeout: int = DEFAULT_TIMEOUT
    ) -> Generator[int]:
        """A free local port forwarded to a Service's port while the context is open."""
        command = self.command(
            "port-forward", f"service/{service}", f":{port}", "--address=127.0.0.1", namespace=namespace
        )
        try:
            process = start_process(command)
        except FileNotFoundError as exc:
            raise KubeError(command, "kubectl not found on PATH") from exc
        try:
            yield forwarded_port(command, process, timeout)
        finally:
            process.terminate()
            process.wait(timeout)

    def secret_value(self, name: str, key: str, *, namespace: str | None = None) -> str:
        """Decoded value of one key of a Kubernetes secret, in the profile namespace unless given."""
        data = decode_secret_data(section(self.get_json("secret", name, namespace=namespace), "data"))
        if key not in data:
            raise KubeError(self.command("get", "secret", name, namespace=namespace), f"no key {key!r}")
        return data[key]


def forwarded_port(command: Sequence[str], process: subprocess.Popen[str], timeout: int) -> int:
    """The local port `kubectl port-forward` reports; KubeError when it exits or reports none in time.

    A thread keeps reading its output: kubectl blocks once a full pipe holds its "Handling connection" lines.
    """
    lines: queue.Queue[str] = queue.Queue()
    output = process.stdout

    def drain() -> None:
        for line in output or ():
            lines.put(line)
        lines.put("")

    threading.Thread(target=drain, daemon=True).start()
    seen: list[str] = []
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            break
        if not line:
            raise KubeError(command, "".join(seen) or "exited")
        if match := FORWARDING.match(line.strip()):
            return int(match.group(1))
        seen.append(line)
    raise KubeError(command, f"no forwarded port within {timeout}s")


def cluster_service(url: str) -> tuple[str, str, int] | None:
    """Service, namespace and port of an http URL on a Service's cluster DNS name; None for any other URL."""
    parts = urlsplit(url)
    match = SERVICE_HOST.match(parts.hostname or "")
    if parts.scheme != "http" or match is None:
        return None
    return match["service"], match["namespace"], parts.port or 80


def decode_secret_data(data: Mapping[str, object]) -> dict[str, str]:
    """The base64 `data` of a Secret, decoded."""
    return {k: base64.b64decode(str(v)).decode() for k, v in data.items()}


def django_value(output: str) -> str:
    """The value a Django shell snippet printed as print("PTEST_VALUE=" + value)."""
    for line in output.splitlines():
        if line.startswith(DJANGO_VALUE_MARKER):
            return line.removeprefix(DJANGO_VALUE_MARKER)
    msg = f"no {DJANGO_VALUE_MARKER} line in Django shell output"
    raise ValueError(msg)


def metadata_name(item: Mapping[str, object]) -> str:
    """metadata.name of a Kubernetes object, or an empty string."""
    return str(section(item, "metadata").get("name", ""))


def context_names(runner: Runner = run_process) -> list[str]:
    """Contexts in the user's kubeconfig."""
    output = run_checked(runner, ["kubectl", "config", "get-contexts", "-o", "name"], DEFAULT_TIMEOUT, KubeError)
    return [line.strip() for line in output.splitlines() if line.strip()]
