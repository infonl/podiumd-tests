"""Everything needed to talk to one environment, built from its profile."""

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

from podiumd_tests.capabilities import Capabilities
from podiumd_tests.capabilities import detect
from podiumd_tests.components import COMPONENTS
from podiumd_tests.credentials import Redactor
from podiumd_tests.credentials import SecretResolver
from podiumd_tests.kube import Kube
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import metadata_name
from podiumd_tests.process import Runner
from podiumd_tests.process import run_process
from podiumd_tests.sessions import make_session

if TYPE_CHECKING:
    from collections.abc import Sequence

    import requests

    from podiumd_tests.config import Profile


WORKLOAD_KINDS = ("deployments", "statefulsets")


class Environment:
    """Profile plus the kubectl, credentials and HTTP access built from it."""

    def __init__(self, profile: Profile, runner: Runner = run_process, environ: dict[str, str] | None = None) -> None:
        self.profile = profile
        self.kube = Kube(profile.kube.context, profile.kube.namespace, runner)
        self.redactor = Redactor()
        self.credentials = SecretResolver(profile, self.kube, self.redactor, runner, environ)

    @property
    def namespaces(self) -> list[str]:
        """Namespaces that hold PodiumD components (application and monitoring)."""
        extra = self.profile.kube.monitoring_namespace
        return [self.profile.kube.namespace, *([extra] if extra else [])]

    def ingress_ip(self) -> str | None:
        """External IP of the ingress service in host-header mode; None in direct mode."""
        ref = self.profile.access.ingress_service
        if self.profile.access.mode != "host-header" or ref is None:
            return None
        ip = self.kube.run(
            "get", "svc", ref.name, "-o", "jsonpath={.status.loadBalancer.ingress[0].ip}", namespace=ref.namespace
        ).strip()
        if not ip:
            raise KubeError(
                self.kube.command("get", "svc", ref.name, namespace=ref.namespace),
                "no external IP (minikube: is `minikube tunnel` running?)",
            )
        return ip

    def session(self) -> requests.Session:
        """HTTP session for the profile URLs."""
        return make_session(self.profile.urls, self.ingress_ip())

    def items(self, kind: str, namespaces: Sequence[str] | None = None) -> list[dict[str, object]]:
        """Objects of one kind in the given namespaces, by default all of the environment's namespaces."""
        found: list[dict[str, object]] = []
        for namespace in self.namespaces if namespaces is None else namespaces:
            found += self.kube.items(kind, namespace=namespace)
        return found

    def workloads(self, namespaces: Sequence[str] | None = None) -> list[dict[str, object]]:
        """The long-running workloads: Deployments and StatefulSets."""
        return [item for kind in WORKLOAD_KINDS for item in self.items(kind, namespaces)]

    @cached_property
    def deployment_names(self) -> list[str]:
        """Names of all deployments in the environment's namespaces; read once."""
        return [metadata_name(d) for d in self.items("deployments")]

    def deployment_for(self, component: str) -> str:
        """The main deployment of a component, e.g. "notificaties" for opennotificaties on some estates."""
        for prefix in COMPONENTS[component].deployment_prefixes:
            if prefix in self.deployment_names:
                return prefix
        msg = f"no deployment for {component} (looked for {', '.join(COMPONENTS[component].deployment_prefixes)})"
        raise KubeError(self.kube.command("get", "deployments"), msg)

    @cached_property
    def capabilities(self) -> Capabilities:
        """Capabilities detected from profile and cluster; profile only when the cluster is unreachable."""
        try:
            names: list[str] | None = self.deployment_names
        except KubeError:
            names = None
        return detect(self.profile, names)
