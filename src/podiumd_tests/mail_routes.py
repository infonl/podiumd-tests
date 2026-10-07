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

if TYPE_CHECKING:
    from podiumd_tests.auth.keycloak_admin import KeycloakAdmin
    from podiumd_tests.config import Profile
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

# Environment variables that name an SMTP host: Django, ZAC, Spring and Quarkus apps.
MAIL_HOST_VARS = frozenset(
    {"EMAIL_HOST", "SMTP_SERVER", "SMTP_HOST", "MAIL_HOST", "SPRING_MAIL_HOST", "QUARKUS_MAILER_HOST"}
)
# Hosts where no SMTP server listens, so mail goes nowhere (Django's default is localhost).
NO_SERVER = frozenset({"", "localhost", "127.0.0.1"})


@dataclass(frozen=True)
class MailRoute:
    """One configured SMTP host and where it is set."""

    where: str
    host: str


def mail_stays_internal(profile: Profile) -> bool:
    """True when the environment's mail may only go to SMTP servers inside the cluster."""
    return MAIL_STAYS_INTERNAL_BY_ESTATE[profile.estate]


def cluster_hosts(env: Environment) -> frozenset[str]:
    """Every name and ClusterIP a Service in the cluster answers on, plus the no-server hosts."""
    hosts = set(NO_SERVER)
    for service in env.kube.items("services", all_namespaces=True):
        name = metadata_name(service)
        namespace = str(section(service, "metadata").get("namespace"))
        hosts |= {name, f"{name}.{namespace}", f"{name}.{namespace}.svc", f"{name}.{namespace}.svc.cluster.local"}
        hosts.add(str(section(service, "spec").get("clusterIP") or ""))
    return frozenset(hosts)


def is_internal(host: str, internal: frozenset[str]) -> bool:
    """The host is a cluster Service or no server at all."""
    return host.lower().rstrip(".") in internal


class _Sources:
    """The mail host values of ConfigMaps and Secrets, each fetched once."""

    def __init__(self, env: Environment) -> None:
        self.env = env
        self.cache: dict[tuple[str, str, str], dict[str, str]] = {}

    def get(self, kind: str, namespace: str, name: str) -> dict[str, str]:
        """The mail host keys of a ConfigMap or Secret ("configmap", "secret")."""
        key = (kind, namespace, name)
        if key not in self.cache:
            data = section(self.env.kube.get_optional(kind, name, namespace=namespace) or {}, "data")
            values = decode_secret_data(data) if kind == "secret" else {k: str(v) for k, v in data.items()}
            # Only mail host values are kept; nothing else of a Secret leaves this class.
            self.cache[key] = {k: v for k, v in values.items() if k in MAIL_HOST_VARS}
        return self.cache[key]

    def value(self, var: JsonObject, namespace: str) -> str:
        """An env entry's value: literal or from a ConfigMap or Secret key."""
        if "value" in var:
            return str(var["value"])
        value_from = section(var, "valueFrom")
        for kind, key in (("configmap", "configMapKeyRef"), ("secret", "secretKeyRef")):
            ref = section(value_from, key)
            if ref:
                return self.get(kind, namespace, str(ref.get("name"))).get(str(ref.get("key")), "")
        return ""


def workload_routes(env: Environment) -> list[MailRoute]:
    """The SMTP hosts the containers of every Deployment and StatefulSet get."""
    sources = _Sources(env)
    routes: list[MailRoute] = []
    for workload in env.workloads():
        namespace = str(section(workload, "metadata").get("namespace") or env.profile.kube.namespace)
        pod = section(section(section(workload, "spec"), "template"), "spec")
        for container in entries(pod.get("containers")):
            where = f"{metadata_name(workload)}/{container.get('name')}"
            for env_from in entries(container.get("envFrom")):
                for kind, key in (("configmap", "configMapRef"), ("secret", "secretRef")):
                    ref = section(env_from, key)
                    if ref:
                        hosts = sources.get(kind, namespace, str(ref.get("name")))
                        routes += [MailRoute(f"{where} {var}", host) for var, host in hosts.items()]
            for var in entries(container.get("env")):
                if var.get("name") in MAIL_HOST_VARS:
                    routes.append(MailRoute(f"{where} {var['name']}", sources.value(var, namespace)))
    return routes


def realm_routes(admins: list[KeycloakAdmin]) -> list[MailRoute]:
    """The SMTP host of each Keycloak realm; a realm without one sends no mail."""
    return [
        MailRoute(f"keycloak realm {admin.realm}", str(section(admin.representation(), "smtpServer").get("host", "")))
        for admin in admins
    ]
