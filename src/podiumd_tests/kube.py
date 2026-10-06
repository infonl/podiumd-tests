"""Thin typed wrapper around the kubectl CLI (PLAN.md §8: why not the Python client).

Every call passes --context and --namespace explicitly, so the current
kubectl context never matters. The command line is kept in errors, so a
failing call can be pasted into a terminal and rerun.
"""

from __future__ import annotations

import base64
import json
import shlex

# Only for subprocess.TimeoutExpired; processes are started in process.py.
import subprocess  # nosec B404

from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.process import Runner
from podiumd_tests.process import run_process

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_TIMEOUT = 30


class KubeError(Exception):
    """kubectl failed or returned something unexpected."""

    def __init__(self, command: Sequence[str], detail: str) -> None:
        self.command = shlex.join(command)
        # kubectl repeats client-side noise (E1005 memcache...) before the real error; keep the last line.
        lines = [line for line in detail.strip().splitlines() if line.strip()]
        super().__init__(f"{self.command}: {lines[-1] if lines else 'failed'}")


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
        self, *args: str, namespace: str | None = None, all_namespaces: bool = False, timeout: int = DEFAULT_TIMEOUT
    ) -> str:
        """Run kubectl and return stdout; KubeError on failure."""
        command = self.command(*args, namespace=namespace, all_namespaces=all_namespaces)
        try:
            result = self.runner(command, timeout)
        except FileNotFoundError as exc:
            raise KubeError(command, "kubectl not found on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise KubeError(command, f"timed out after {timeout}s") from exc
        if result.returncode != 0:
            raise KubeError(command, result.stderr or f"exit code {result.returncode}")
        return result.stdout

    def get_json(self, *args: str, namespace: str | None = None, all_namespaces: bool = False) -> dict[str, object]:
        """`kubectl get ... -o json` as a dict."""
        out = self.run("get", *args, "-o", "json", namespace=namespace, all_namespaces=all_namespaces)
        try:
            data: object = json.loads(out)
        except json.JSONDecodeError as exc:
            raise KubeError(self.command("get", *args), f"invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise KubeError(self.command("get", *args), "expected a JSON object")
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

    def exec_django_shell(self, deployment: str, code: str, timeout: int = 60) -> str:
        """Run Python code in `manage.py shell` of a Django deployment; return its stdout."""
        return self.run(
            "exec", f"deploy/{deployment}", "--", "python", "manage.py", "shell", "-c", code, timeout=timeout
        )

    def secret_value(self, name: str, key: str) -> str:
        """Decoded value of one key of a Kubernetes secret."""
        data = self.get_json("secret", name).get("data")
        if not isinstance(data, dict) or key not in data:
            raise KubeError(self.command("get", "secret", name), f"no key {key!r}")
        return base64.b64decode(str(cast("dict[str, object]", data)[key])).decode()


def metadata_name(item: dict[str, object]) -> str:
    """metadata.name of a Kubernetes object, or an empty string."""
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        return str(cast("dict[str, object]", metadata).get("name", ""))
    return ""


def context_names(runner: Runner = run_process) -> list[str]:
    """Contexts in the user's kubeconfig."""
    command = ["kubectl", "config", "get-contexts", "-o", "name"]
    try:
        result = runner(command, DEFAULT_TIMEOUT)
    except FileNotFoundError as exc:
        raise KubeError(command, "kubectl not found on PATH") from exc
    if result.returncode != 0:
        raise KubeError(command, result.stderr)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
