"""Everything needed to talk to one environment, built from its profile."""

from __future__ import annotations

import tempfile

from contextlib import ExitStack
from contextlib import contextmanager
from contextlib import suppress
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from podiumd_tests.capabilities import Capabilities
from podiumd_tests.capabilities import detect
from podiumd_tests.cilium import detect_network
from podiumd_tests.components import COMPONENTS
from podiumd_tests.components import DJANGO_APPS
from podiumd_tests.credentials import Redactor
from podiumd_tests.credentials import SecretResolver
from podiumd_tests.json_data import section
from podiumd_tests.kube import LOOPBACK
from podiumd_tests.kube import Kube
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import cluster_service
from podiumd_tests.kube import metadata_name
from podiumd_tests.process import Runner
from podiumd_tests.process import run_process
from podiumd_tests.sessions import agreed_cipher
from podiumd_tests.sessions import announced_body_status
from podiumd_tests.sessions import make_session
from podiumd_tests.sessions import peer_certificate

if TYPE_CHECKING:
    import ssl

    from collections.abc import Generator
    from collections.abc import Sequence

    import requests

    from podiumd_tests.config import Profile


WORKLOAD_KINDS = ("deployments", "statefulsets")


class Environment:
    """Profile plus the kubectl, credentials and HTTP access built from it."""

    def __init__(self, profile: Profile, runner: Runner = run_process, environ: dict[str, str] | None = None) -> None:
        self.profile: Profile = profile
        self.kube: Kube = Kube(profile.kube.context, profile.kube.namespace, runner)
        self.redactor: Redactor = Redactor()
        self.credentials: SecretResolver = SecretResolver(profile, self.kube, self.redactor, environ)

    @property
    def namespaces(self) -> list[str]:
        """Namespaces that hold PodiumD components (application and monitoring)."""
        extra = self.profile.kube.monitoring_namespace
        return [self.profile.kube.namespace, *([extra] if extra else [])]

    @cached_property
    def ca_file(self) -> str | None:
        """File with the profile's access.ca_bundle, fetched from the cluster once; None: the system's CAs."""
        ref = self.profile.access.ca_bundle
        if ref is None:
            return None
        configmap = self.kube.get_json("configmap", ref.configmap)
        bundle = str(section(configmap, "data").get(ref.key) or "")
        if not bundle:
            raise KubeError(self.kube.command("get", "configmap", ref.configmap), f"no key {ref.key}")
        path = Path(tempfile.gettempdir()) / f"podiumd-tests-{self.profile.name}-ca.pem"
        # Parallel test workers share this file: write a private copy and rename it into place, so
        # no worker ever reads a half-written bundle ("[X509] PEM lib").
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            handle.write(bundle)
        Path(handle.name).replace(path)
        return str(path)

    @cached_property
    def deployment_names(self) -> list[str]:
        """Names of all deployments in the environment's namespaces; read once."""
        return [metadata_name(deployment) for deployment in self.items("deployments")]

    @cached_property
    def workload_names(self) -> list[str]:
        """Names of all Deployments and, where listable, StatefulSets (e.g. OpenBao); for capability detection."""
        names = list(self.deployment_names)
        with suppress(KubeError):
            names += [metadata_name(statefulset) for statefulset in self.items("statefulsets")]
        return names

    @cached_property
    def capabilities(self) -> Capabilities:
        """Capabilities detected from profile and cluster; profile only when the cluster is unreachable."""
        try:
            names: list[str] | None = self.workload_names
        except KubeError:
            return detect(self.profile, None)
        return detect(self.profile, names, detect_network(self.kube))

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
                "no external IP: on minikube, run `minikube tunnel`",
            )
        return ip

    def peer_certificate(self, url: str) -> dict[str, object]:
        """Return the verified certificate the host of an https profile URL presents."""
        return peer_certificate(url, self.ingress_ip(), self.ca_file)

    def agreed_cipher(self, url: str, version: ssl.TLSVersion, ciphers: str) -> str | None:
        """Return the cipher suite the host of an https profile URL agrees to (sessions.agreed_cipher)."""
        return agreed_cipher(url, version, ciphers, self.ingress_ip(), self.ca_file)

    def announced_body_status(self, url: str, size: int) -> int | None:
        """Return the status of a POST to a profile URL that announces size bytes (sessions.announced_body_status)."""
        return announced_body_status(url, size, self.ingress_ip(), self.ca_file)

    def session(self, *, cookies: bool = True) -> requests.Session:
        """HTTP session for the profile URLs; cookies=False for token APIs."""
        return make_session(self.profile.urls, self.ingress_ip(), cookies=cookies, verify=self.ca_file)

    @contextmanager
    def console_urls(self) -> Generator[dict[str, str]]:
        """Yield the profile URLs as this console reaches them: a present component's in-cluster URL by port-forward."""
        urls = dict(self.profile.urls)
        with ExitStack() as forwards:
            for component, url in self.profile.urls.items():
                service = cluster_service(url)
                if service is None or component not in self.capabilities.present:
                    continue
                name, namespace, port = service
                local = forwards.enter_context(self.kube.port_forward(name, port, namespace=namespace))
                urls[component] = urlunsplit(urlsplit(url)._replace(netloc=f"{LOOPBACK}:{local}"))
            yield urls

    def items(self, kind: str, namespaces: Sequence[str] | None = None) -> list[dict[str, object]]:
        """Objects of one kind in the given namespaces, by default all of the environment's namespaces."""
        selected = self.namespaces if namespaces is None else namespaces
        return [item for namespace in selected for item in self.kube.items(kind, namespace=namespace)]

    def workloads(self, namespaces: Sequence[str] | None = None) -> list[dict[str, object]]:
        """Return the long-running workloads: Deployments and StatefulSets."""
        return [item for kind in WORKLOAD_KINDS for item in self.items(kind, namespaces)]

    def deployment_for(self, component: str) -> str:
        """Return the main deployment of a component, e.g. "notificaties" for opennotificaties on podiumd-infra."""
        for prefix in COMPONENTS[component].deployment_prefixes:
            if prefix in self.deployment_names:
                return prefix
        msg = f"no deployment for {component} (looked for {', '.join(COMPONENTS[component].deployment_prefixes)})"
        raise KubeError(self.kube.command("get", "deployments"), msg)

    def variable(self, component: str, name: str) -> str:
        """Return an environment variable of the component's main deployment, e.g. GEMEENTE_MAIL of zac."""
        return self.kube.exec(self.deployment_for(component), "printenv", name, timeout=30).strip()

    def admin_of(self, component: str) -> str:
        """Return the Django app whose admin serves this one's: objecten for objecttypen on Open Object, else itself.

        Open Object's Keycloak client accepts only objecten's host as redirect URI.
        """
        try:
            return self._sharing_deployment(component)
        except KubeError:  # no cluster, or an app without deployment: the profile URL decides
            return component

    def _sharing_deployment(self, component: str) -> str:
        """Return the first Django app of the profile that runs on the component's deployment, else the component."""
        mine = self.deployment_for(component)
        return next(
            (app for app in DJANGO_APPS if app in self.profile.urls and self.deployment_for(app) == mine), component
        )
