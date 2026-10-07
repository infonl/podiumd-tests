"""podiumd-tests' webhook receiver in the cluster (infra/webhook-receiver), and reading what it received.

The receiver answers every POST with 204 and appends it to a JSON-lines file; tests read that
file through `kubectl exec`, so the receiver needs no ingress. Each test uses its own callback
path, which keeps parallel tests apart.
"""

from __future__ import annotations

import json
import secrets

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import cast

import yaml

from podiumd_tests.config import REPO_ROOT
from podiumd_tests.kube import metadata_name
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.bootstrap import Context
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

NAME = "ptest-bootstrap-webhook-receiver"
INFRA = REPO_ROOT / "infra" / "webhook-receiver"
RECEIVED_FILE = "/data/received.jsonl"
ROLLOUT_TIMEOUT = 180


def manifests() -> list[dict[str, object]]:
    """The receiver's ConfigMap, Deployment and Service, with receiver.py in the ConfigMap."""
    docs = [cast("dict[str, object]", d) for d in yaml.safe_load_all((INFRA / "manifests.yaml").read_text()) if d]
    for doc in docs:
        if doc["kind"] == "ConfigMap":
            doc["data"] = {"receiver.py": (INFRA / "receiver.py").read_text()}
    return docs


@dataclass(frozen=True)
class Callback:
    """One test's callback path on the receiver."""

    env: Environment
    path: str

    @classmethod
    def new(cls, env: Environment, run_tag: str) -> Callback:
        """A callback path of its own, under the run tag."""
        return cls(env, f"/{run_tag}/{secrets.token_hex(6)}")

    @property
    def url(self) -> str:
        """URL the platform reaches the callback on from inside the cluster."""
        return f"http://{NAME}.{self.env.profile.kube.namespace}{self.path}"

    def received(self) -> list[JsonObject]:
        """Everything the receiver got on this path, oldest first."""
        out = self.env.kube.exec(NAME, "sh", "-c", f"cat {RECEIVED_FILE} 2>/dev/null || true")
        entries = [cast("JsonObject", json.loads(line)) for line in out.splitlines() if line.strip()]
        return [e for e in entries if e.get("path") == self.path]

    def wait_for(self, match: Callable[[JsonObject], bool], *, timeout: float, description: str) -> JsonObject:
        """The first received entry that matches; WaitTimeoutError when none arrives in time."""
        return wait_until(
            lambda: next((e for e in self.received() if match(e)), None), timeout=timeout, description=description
        )


@dataclass(frozen=True)
class WebhookReceiver:
    """Bootstrap step: deploy the receiver; it is present when its Deployment is ready and runs the current code."""

    name: str = "infra-webhook-receiver"
    requires: tuple[str, ...] = ("cluster",)
    wiring: bool = False

    def is_present(self, ctx: Context, /) -> bool:
        """The ConfigMap holds the current receiver.py and the Deployment has a ready replica."""
        kube = ctx.env.kube
        config_map = kube.get_optional("configmap", NAME)
        deployment = kube.get_optional("deployment", NAME)
        if config_map is None or deployment is None:
            return False
        code = cast("dict[str, object]", config_map.get("data") or {}).get("receiver.py")
        ready = cast("dict[str, object]", deployment.get("status") or {}).get("readyReplicas")
        return code == (INFRA / "receiver.py").read_text() and bool(ready)

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Apply the manifests, restart on new code, and wait until the Deployment is ready."""
        kube = ctx.env.kube
        for manifest in manifests():
            kube.apply(manifest)
        kube.run("rollout", "restart", f"deployment/{NAME}")
        kube.run(
            "rollout", "status", f"deployment/{NAME}", f"--timeout={ROLLOUT_TIMEOUT}s", timeout=ROLLOUT_TIMEOUT + 10
        )
        return {}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Delete the manifests' objects."""
        for manifest in reversed(manifests()):
            ctx.env.kube.delete(str(manifest["kind"]).lower(), metadata_name(manifest))
        return ()
