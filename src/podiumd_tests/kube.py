"""Thin typed wrapper around the kubectl CLI (PLAN.md §8: why not the Python client).

Every call passes --context and --namespace explicitly, so the current
kubectl context never matters. The command line is kept in errors, so a
failing call can be pasted into a terminal and rerun.
"""

from __future__ import annotations

import base64
import json

from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.process import ProcessError
from podiumd_tests.process import Runner
from podiumd_tests.process import run_checked
from podiumd_tests.process import run_process

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULT_TIMEOUT = 30
# All Maykin images (Open Zaak, Open Klant, Objecten, Open Inwoner, ...) have their Django project here.
MANAGE_PY = "/app/src/manage.py"
DJANGO_VALUE_MARKER = "PTEST_VALUE="


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
        self, *args: str, namespace: str | None = None, all_namespaces: bool = False, timeout: int = DEFAULT_TIMEOUT
    ) -> str:
        """Run kubectl and return stdout; KubeError on failure."""
        command = self.command(*args, namespace=namespace, all_namespaces=all_namespaces)
        return run_checked(self.runner, command, timeout, KubeError)

    def get_json(self, *args: str, namespace: str | None = None, all_namespaces: bool = False) -> dict[str, object]:
        """`kubectl get ... -o json` as a dict."""
        args = ("get", *args, "-o", "json")
        out = self.run(*args, namespace=namespace, all_namespaces=all_namespaces)
        try:
            data: object = json.loads(out)
        except json.JSONDecodeError as exc:
            raise KubeError(
                self.command(*args, namespace=namespace, all_namespaces=all_namespaces), f"invalid JSON: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise KubeError(
                self.command(*args, namespace=namespace, all_namespaces=all_namespaces), "expected a JSON object"
            )
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
        """Run Python code in `manage.py shell` of a Django deployment; return its stdout.

        The stdout also holds Django's own chatter ("118 objects imported
        automatically"); use django_value() to pick out one printed value.
        """
        return self.run("exec", f"deploy/{deployment}", "--", "python", MANAGE_PY, "shell", "-c", code, timeout=timeout)

    def secret_value(self, name: str, key: str) -> str:
        """Decoded value of one key of a Kubernetes secret."""
        data = self.get_json("secret", name).get("data")
        if not isinstance(data, dict) or key not in data:
            raise KubeError(self.command("get", "secret", name), f"no key {key!r}")
        return base64.b64decode(str(cast("dict[str, object]", data)[key])).decode()


def django_value(output: str) -> str:
    """The value a Django shell snippet printed as print("PTEST_VALUE=" + value)."""
    for line in output.splitlines():
        if line.startswith(DJANGO_VALUE_MARKER):
            return line.removeprefix(DJANGO_VALUE_MARKER)
    msg = f"no {DJANGO_VALUE_MARKER} line in Django shell output"
    raise ValueError(msg)


def metadata_name(item: Mapping[str, object]) -> str:
    """metadata.name of a Kubernetes object, or an empty string."""
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        return str(cast("dict[str, object]", metadata).get("name", ""))
    return ""


def context_names(runner: Runner = run_process) -> list[str]:
    """Contexts in the user's kubeconfig."""
    output = run_checked(runner, ["kubectl", "config", "get-contexts", "-o", "name"], DEFAULT_TIMEOUT, KubeError)
    return [line.strip() for line in output.splitlines() if line.strip()]
