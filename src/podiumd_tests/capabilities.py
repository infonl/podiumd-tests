"""What an environment can do, detected at runtime instead of from a release number (PLAN.md §5).

A component is a capability when the profile has a URL for it and, when the
cluster can be read, a deployment for it exists. "cluster" is a capability
too: the kube API can be read from this console. Tests declare their needs
with @pytest.mark.requires("oab", ...) and skip with a reason otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from podiumd_tests.components import COMPONENTS
from podiumd_tests.components import deployed_components

if TYPE_CHECKING:
    from podiumd_tests.config import Profile

COMPONENT_NAMES = frozenset(COMPONENTS)
COMPONENTS_WITH_DEPLOYMENT = frozenset(n for n, c in COMPONENTS.items() if c.deployment_prefixes)
CLUSTER = "cluster"


@dataclass(frozen=True)
class Capabilities:
    """Capabilities that are present, and why the others are absent."""

    present: frozenset[str]
    reasons: dict[str, str]

    def missing(self, *needed: str) -> list[str]:
        """The needed capabilities that are absent."""
        return [n for n in needed if n not in self.present]

    def skip_reason(self, *needed: str) -> str | None:
        """Skip reason when any needed capability is absent, else None."""
        absent = self.missing(*needed)
        if not absent:
            return None
        return "requires: " + ", ".join(f"{n} ({self.reasons.get(n, 'not detected')})" for n in absent)


def detect(profile: Profile, deployment_names: list[str] | None) -> Capabilities:
    """deployment_names=None means the cluster could not be read; then the profile alone decides."""
    configured = set(profile.urls)
    reasons = dict.fromkeys(COMPONENT_NAMES - configured, "no URL in profile")
    if deployment_names is None:
        reasons[CLUSTER] = f"kube API of context {profile.kube.context} not reachable from this console"
        return Capabilities(frozenset(configured), reasons)
    deployed = deployed_components(deployment_names)
    # Components without their own deployment (e.g. keycloak-admin) follow their URL only.
    for component in configured - deployed:
        if component in COMPONENTS_WITH_DEPLOYMENT:
            reasons[component] = f"no deployment in namespace {profile.kube.namespace}"
    present = {c for c in configured if c in deployed or c not in COMPONENTS_WITH_DEPLOYMENT}
    present.add(CLUSTER)
    return Capabilities(frozenset(present), reasons)
