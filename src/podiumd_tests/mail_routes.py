"""Where the environment's apps send mail: the SMTP host of every workload and Keycloak realm.

A host inside the cluster is a sink (Mailpit or another); anything else is a real SMTP server.
An in-cluster relay that forwards to a real server is not detected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from podiumd_tests.config import MAIL_STAYS_INTERNAL_BY_ESTATE
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kube import decode_secret_data
from podiumd_tests.kube import metadata_name
from podiumd_tests.kube import metadata_namespace

if TYPE_CHECKING:
    from podiumd_tests.auth.keycloak_admin import KeycloakAdmin
    from podiumd_tests.config import Profile
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

# Environment variables that name an SMTP host: Django, ZAC, Spring and Quarkus apps.
MAIL_HOST_VARS = frozenset(
    ("EMAIL_HOST", "SMTP_SERVER", "SMTP_HOST", "MAIL_HOST", "SPRING_MAIL_HOST", "QUARKUS_MAILER_HOST")
)
# Hosts where no SMTP server listens, so mail goes nowhere (Django's default is localhost).
NO_SERVER = frozenset(("", "localhost", "127.0.0.1"))


@dataclass(frozen=True)
class MailRoute:
    """One configured SMTP host and where it is set."""

    where: str
    host: str


def mail_stays_internal(profile: Profile) -> bool:
    """Return True when the environment's mail may only go to SMTP servers inside the cluster."""
    return MAIL_STAYS_INTERNAL_BY_ESTATE[profile.estate]


def cluster_hosts(env: Environment) -> frozenset[str]:
    """Every name and ClusterIP a Service in the cluster answers on, plus the no-server hosts."""
    hosts = set(NO_SERVER)
    for service in env.kube.items("services", all_namespaces=True):
        name = metadata_name(service)
        namespace = metadata_namespace(service)
        hosts |= {name, f"{name}.{namespace}", f"{name}.{namespace}.svc", f"{name}.{namespace}.svc.cluster.local"}
        hosts.add(str(section(service, "spec").get("clusterIP") or ""))
    return frozenset(hosts)


def is_internal(host: str, internal: frozenset[str]) -> bool:
    """Return whether the host is a cluster Service or no server at all."""
    return host.lower().rstrip(".") in internal


def _texts(kind: str, data: JsonObject) -> dict[str, str]:
    """Return the values of a Secret's data, decoded, or of a ConfigMap's."""
    if kind == "secret":
        return decode_secret_data(data)
    return {var: str(host) for var, host in data.items()}


class _Sources:
    """The mail host values of ConfigMaps and Secrets, each fetched once."""

    def __init__(self, env: Environment) -> None:
        self.env: Environment = env
        self.cache: dict[tuple[str, str, str], dict[str, str]] = {}

    def get(self, kind: str, namespace: str, name: str) -> dict[str, str]:
        """Return the mail host keys of a ConfigMap or Secret ("configmap", "secret")."""
        key = (kind, namespace, name)
        if key not in self.cache:
            data = section(self.env.kube.get_optional(kind, name, namespace=namespace) or {}, "data")
            values = _texts(kind, data)
            # Only mail host values are kept; nothing else of a Secret leaves this class.
            self.cache[key] = {var: host for var, host in values.items() if var in MAIL_HOST_VARS}
        return self.cache[key]

    def value(self, var: JsonObject, namespace: str) -> str:
        """Return an env entry's value: literal or from a ConfigMap or Secret key."""
        if "value" in var:
            return str(var["value"])
        value_from = section(var, "valueFrom")
        for kind, key in (("configmap", "configMapKeyRef"), ("secret", "secretKeyRef")):
            ref = section(value_from, key)
            if ref:
                hosts = self.get(kind, namespace, str(ref.get("name")))
                return hosts.get(str(ref.get("key")), "")
        return ""

    def env_from(self, env_from: JsonObject, namespace: str) -> list[tuple[str, str]]:
        """Return the mail host keys of an envFrom entry's ConfigMap and Secret."""
        found: list[tuple[str, str]] = []
        for kind, key in (("configmap", "configMapRef"), ("secret", "secretRef")):
            ref = section(env_from, key)
            if ref:
                found += self.get(kind, namespace, str(ref.get("name"))).items()
        return found


def workload_routes(env: Environment) -> list[MailRoute]:
    """Return the SMTP hosts the containers of every Deployment and StatefulSet get."""
    sources = _Sources(env)
    routes: list[MailRoute] = []
    for workload in env.workloads():
        namespace = str(section(workload, "metadata").get("namespace") or env.profile.kube.namespace)
        pod = section(section(section(workload, "spec"), "template"), "spec")
        for container in entries(pod.get("containers")):
            where = f"{metadata_name(workload)}/{container.get('name')}"
            routes += _container_routes(sources, where, container, namespace)
    return routes


def _container_routes(sources: _Sources, where: str, container: JsonObject, namespace: str) -> list[MailRoute]:
    routes: list[MailRoute] = []
    for env_from in entries(container.get("envFrom")):
        hosts = sources.env_from(env_from, namespace)
        routes += [MailRoute(f"{where} {var}", host) for var, host in hosts]
    for var in entries(container.get("env")):
        if var.get("name") in MAIL_HOST_VARS:
            routes.append(MailRoute(f"{where} {var['name']}", sources.value(var, namespace)))
    return routes


def realm_routes(admins: list[KeycloakAdmin]) -> list[MailRoute]:
    """Return the SMTP host of each Keycloak realm; a realm without one sends no mail."""
    return [
        MailRoute(f"keycloak realm {admin.realm}", str(section(admin.representation(), "smtpServer").get("host", "")))
        for admin in admins
    ]
