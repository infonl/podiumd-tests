"""Canonical PodiumD component names and the names they go by in the environments.

Profiles, capability detection and `env init` all use the canonical name
(the key of COMPONENTS). Host aliases differ per estate: KISS is "contact",
Open Inwoner is "portaal" (podiumd-infra) or "mijn" (ExternalsPodiumD).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Component:
    """How one component shows up in hostnames, workload names and Prometheus."""

    host_aliases: tuple[str, ...]
    deployment_prefixes: tuple[str, ...]
    # Prometheus scrapes it through a ServiceMonitor or PodMonitor named like one of its workloads.
    monitored: bool = False
    # Its OTEL service.name, which the collector's remote write turns into the series' job label.
    otel_service: str = ""


COMPONENTS: dict[str, Component] = {
    "zac": Component(("zac",), ("zac",)),
    "openzaak": Component(("openzaak",), ("openzaak",), otel_service="openzaak"),
    "keycloak": Component(("keycloak",), ("keycloak",), monitored=True),
    "keycloak-admin": Component(("keycloak-admin",), ()),
    "kiss": Component(("contact", "kiss"), ("contact", "contact-web", "kiss")),
    "ita": Component(("ita", "internetaakafhandeling"), ("ita", "ita-web")),
    "pabc": Component(("pabc",), ("pabc",)),
    "openarchiefbeheer": Component(
        ("abc", "openarchiefbeheer", "openarchiefbeheer-ui"), ("openarchiefbeheer",), otel_service="openarchiefbeheer"
    ),
    "openinwoner": Component(("portaal", "mijn", "openinwoner"), ("openinwoner",), otel_service="openinwoner"),
    "openformulieren": Component(
        ("formulier", "openformulieren", "openformulieren-nginx"), ("openformulieren",), otel_service="openforms"
    ),
    "openklant": Component(("openklant",), ("openklant",), otel_service="openklant"),
    "objecten": Component(("objecten",), ("objecten",), otel_service="openobject"),
    # Open Object (podiumd 4.10) serves the Objecttypen API from deployment objecten.
    "objecttypen": Component(("objecttypen",), ("objecttypen", "objecten")),
    "opennotificaties": Component(
        ("notificaties", "opennotificaties"), ("opennotificaties", "notificaties"), otel_service="opennotificaties"
    ),
    "omc": Component(("omc",), ("omc",)),
    "openbeheer": Component(("openbeheer",), ("openbeheer",)),
    "referentielijsten": Component(("referentielijsten",), ("referentielijsten",), otel_service="referentielijsten"),
    "openvtb": Component(("openvtb",), ("openvtb",), otel_service="openvtb"),
    # The sub-chart names its deployment <helm release>-zaakbrug.
    "zaakbrug": Component(("zaakbrug",), ("zaakbrug", "podiumd-zaakbrug")),
    # ExternalsPodiumD's host is <stage>-office-addin.<domain>.
    "zgw-office-addin": Component(("office-addin", "zgw-office-addin"), ("zgw-office-addin",)),
    "frankgateway": Component(
        ("frankgateway",), ("frankgateway-outway", "frankgateway", "frank-gateway"), monitored=True
    ),
    # The chart names its StatefulSet and ServiceMonitor <helm release>-openbao.
    "openbao": Component(("openbao",), ("openbao", "podiumd-openbao", "podiumd-minikube-openbao"), monitored=True),
    # podiumd's nginx in front of BRP, KvK and BAG (Frank!Gateway replaces it in newer charts).
    "api-proxy": Component(("api-proxy",), ("api-proxy",)),
    # monitoring-logging's Grafana is named <helm release>-grafana: release monitoring or monitoring-logging on
    # the estates, podiumd-minikube on minikube.
    "grafana": Component(
        ("grafana", "podiumd-logs"),
        ("grafana", "monitoring-grafana", "monitoring-logging-grafana", "podiumd-minikube-grafana"),
    ),
    "mailpit": Component(("mailpit",), ("mailpit",)),
    # Without a URL: found by their workloads only.
    "eck-operator": Component((), ("elastic-operator",), monitored=True),
    "redis": Component((), ("redis-ha",), monitored=True),
    "clamav": Component((), ("clamav",), monitored=True),
}

# Components that are Django apps: they have /admin/, `manage.py shell` and Django's mail settings.
DJANGO_APPS = (
    "openzaak",
    "openklant",
    "openformulieren",
    "openinwoner",
    "openarchiefbeheer",
    "objecten",
    "objecttypen",
    "opennotificaties",
)


def _component_for_label(label: str) -> str | None:
    for name, component in COMPONENTS.items():
        if label in component.host_aliases:
            return name
    return None


def component_for_host(host: str) -> str | None:
    """Component of a hostname: <app>.<env>.<domain>, <stage>-<app>.<domain> or <app>.local."""
    label = host.split(".", 1)[0]
    found = _component_for_label(label)
    if found is None and "-" in label:
        found = _component_for_label(label.split("-", 1)[1])
    return found


def deployed_components(deployment_names: list[str]) -> set[str]:
    """Canonical names of the components that have at least one deployment."""
    found: set[str] = set()
    for name, component in COMPONENTS.items():
        for prefix in component.deployment_prefixes:
            if any(d == prefix or d.startswith(f"{prefix}-") for d in deployment_names):
                found.add(name)
    return found
