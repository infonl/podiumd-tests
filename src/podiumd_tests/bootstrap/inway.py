"""Bootstrap of the inway's consumer tests where podiumd-tests owns them (profile setting inway_client_ca).

fg-echo is the upstream of the inway's /echo/* route; the identities are client certificates signed by the edge's
client CA; partner-a and partner-b are registered as consumers in OpenBao through the environment owner's command
(profile setting inway_consumers_command). On kees00 podiumd-infra's waf-mtls-check --setup owns all of this.
"""

from __future__ import annotations

import tempfile

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from typing import cast

import yaml

from podiumd_tests.config import REPO_ROOT
from podiumd_tests.inway import IDENTITIES
from podiumd_tests.inway import fingerprint
from podiumd_tests.inway import make_identity
from podiumd_tests.inway import secret_name
from podiumd_tests.inway import split
from podiumd_tests.process import run_checked

if TYPE_CHECKING:
    from podiumd_tests.bootstrap.runner import Context

FG_ECHO = REPO_ROOT / "infra" / "fg-echo" / "manifests.yaml"
CLIENT_CA = "inway_client_ca"
CONSUMERS_COMMAND = "inway_consumers_command"
CONSUMERS = ("partner-a", "partner-b")
ROLLOUT_TIMEOUT = 120
CONSUMERS_TIMEOUT = 180


def fg_echo_manifests() -> list[dict[str, object]]:
    """Return fg-echo's ConfigMap, Deployment and Service."""
    return [cast("dict[str, object]", doc) for doc in yaml.safe_load_all(FG_ECHO.read_text()) if doc]


@dataclass(frozen=True)
class InwayConsumers:
    """Bootstrap step: fg-echo, client certificates partner-a/b/c, and partner-a and partner-b as consumers."""

    name: str = "inway-consumers"
    requires: tuple[str, ...] = ("cluster", "inway")
    wiring: bool = False

    def is_present(self, ctx: Context, /) -> bool:
        """Return whether fg-echo runs and every identity is stored, or the profile leaves them to their owner."""
        if self._paths(ctx) is None:
            return True
        deployment = ctx.env.kube.get_optional("deployment", "fg-echo")
        status = cast("dict[str, object]", (deployment or {}).get("status") or {})
        stored = ctx.store.read()
        return bool(status.get("readyReplicas")) and all(secret_name(name) in stored for name in IDENTITIES)

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Deploy fg-echo, make the identities and register partner-a and partner-b; the identities to store."""
        paths = self._paths(ctx)
        if paths is None:
            ctx.notes.append(f"profile has no {CLIENT_CA}: fg-echo and the identities are the environment owner's")
            return {}
        client_ca, command = paths
        ctx.env.kube.deploy(fg_echo_manifests(), "fg-echo", ROLLOUT_TIMEOUT)
        with tempfile.TemporaryDirectory() as directory:
            made = {name: make_identity(ctx.env.kube.runner, client_ca, Path(directory), name) for name in IDENTITIES}
        pairs = [f"{name}={fingerprint(split(made[name])[0])}" for name in CONSUMERS]
        run_checked(ctx.env.kube.runner, [command, *pairs], CONSUMERS_TIMEOUT)
        return {secret_name(name): pem for name, pem in made.items()}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Unregister partner-a and partner-b and delete fg-echo; the stored identities go with the step."""
        paths = self._paths(ctx)
        if paths is None:
            return ()
        run_checked(ctx.env.kube.runner, [paths[1], "--remove", *CONSUMERS], CONSUMERS_TIMEOUT)
        ctx.env.kube.delete_all(fg_echo_manifests())
        return tuple(secret_name(name) for name in IDENTITIES)

    def _paths(self, ctx: Context) -> tuple[Path, str] | None:
        """Return the client CA (without .crt/.key) and the consumer command; None when the profile has no CA."""
        settings = ctx.env.profile.settings
        if not settings.get(CLIENT_CA):
            return None
        if not settings.get(CONSUMERS_COMMAND):
            msg = f"{self.name}: profile {ctx.env.profile.name} sets {CLIENT_CA} but not {CONSUMERS_COMMAND}"
            raise ValueError(msg)
        # Relative to the directory that holds podiumd-tests.
        return REPO_ROOT.parent / settings[CLIENT_CA], str(REPO_ROOT.parent / settings[CONSUMERS_COMMAND])
