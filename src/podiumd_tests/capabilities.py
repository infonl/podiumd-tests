"""What an environment can do, detected at runtime instead of from a release number.

A component is a capability when the profile has a URL for it and, when the
cluster can be read, a deployment for it exists. A URL on a Service's cluster
DNS name needs the cluster too: the console reaches it through a port-forward. "cluster" is a capability
too: the kube API can be read from this console; so are "cilium" and "hubble" when the
cluster runs them. Tests declare their needs
with @pytest.mark.requires("openzaak", ...) and skip with a reason otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from podiumd_tests.cilium import CILIUM
from podiumd_tests.cilium import HUBBLE
from podiumd_tests.components import COMPONENTS
from podiumd_tests.components import HOSTED
from podiumd_tests.components import deployed_components
from podiumd_tests.kube import cluster_service

if TYPE_CHECKING:
    from podiumd_tests.config import Profile

COMPONENTS_WITH_DEPLOYMENT = frozenset(name for name, component in COMPONENTS.items() if component.deployment_prefixes)
CLUSTER = "cluster"
NETWORK = (CILIUM, HUBBLE)


@dataclass(frozen=True)
class Capabilities:
    """Capabilities that are present, and why the others are absent."""

    present: frozenset[str]
    reasons: dict[str, str]

    def missing(self, *needed: str) -> list[str]:
        """The needed capabilities that are absent."""
        return [name for name in needed if name not in self.present]

    def skip_reason(self, *needed: str) -> str | None:
        """Skip reason when any needed capability is absent, else None."""
        absent = self.missing(*needed)
        if not absent:
            return None
        explained = ", ".join(f"{name} ({self.reasons.get(name, 'not detected')})" for name in absent)
        return f"requires: {explained}"


def detect(
    profile: Profile,
    deployment_names: list[str] | None,
    network: tuple[frozenset[str], dict[str, str]] | None = None,
) -> Capabilities:
    """Capabilities of an environment; with deployment_names=None (cluster unreadable) the profile alone decides.

    network: the cluster's network capabilities and the reasons for the absent ones (cilium.detect_network).
    """
    configured = set(profile.urls)
    reasons = dict.fromkeys(set(HOSTED) - configured, "no URL in profile")
    if deployment_names is None:
        reasons[CLUSTER] = f"kube API of context {profile.kube.context} not reachable from this console"
        reasons.update(dict.fromkeys(NETWORK, "kube API not reachable"))
        in_cluster = {component for component in configured if cluster_service(profile.urls[component])}
        reasons.update(dict.fromkeys(in_cluster, "in-cluster URL, and the kube API is not reachable"))
        return Capabilities(frozenset(configured - in_cluster), reasons)
    deployed = deployed_components(deployment_names)
    namespaces = " or ".join(
        namespace for namespace in (profile.kube.namespace, profile.kube.monitoring_namespace) if namespace
    )
    # Components without their own deployment (e.g. keycloak-admin) follow their URL only.
    for component in configured - deployed:
        if component in COMPONENTS_WITH_DEPLOYMENT:
            reasons[component] = f"no deployment in namespace {namespaces}"
    present = {
        component for component in configured if component in deployed or component not in COMPONENTS_WITH_DEPLOYMENT
    }
    present.add(CLUSTER)
    if network:
        present |= network[0]
        reasons.update(network[1])
    return Capabilities(frozenset(present), reasons)
