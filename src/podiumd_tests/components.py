"""Canonical PodiumD component names and the names they go by in the environments.

Profiles, capability detection and `env init` all use the canonical name
(the key of COMPONENTS). Host aliases differ per estate: KISS is "contact",
Open Inwoner is "portaal" (podiumd-infra) or "mijn" (ExternalsPodiumD).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Component:
    """How one component shows up in hostnames and deployment names."""

    host_aliases: tuple[str, ...]
    deployment_prefixes: tuple[str, ...]


COMPONENTS: dict[str, Component] = {
    "zac": Component(("zac",), ("zac",)),
    "openzaak": Component(("openzaak",), ("openzaak",)),
    "keycloak": Component(("keycloak",), ("keycloak",)),
    "keycloak-admin": Component(("keycloak-admin",), ()),
    "kiss": Component(("contact", "kiss"), ("kiss",)),
    "ita": Component(("ita", "internetaakafhandeling"), ("ita",)),
    "pabc": Component(("pabc",), ("pabc",)),
    "openarchiefbeheer": Component(("abc", "openarchiefbeheer", "openarchiefbeheer-ui"), ("openarchiefbeheer",)),
    "openinwoner": Component(("portaal", "mijn", "openinwoner"), ("openinwoner",)),
    "openformulieren": Component(("formulier", "openformulieren", "openformulieren-nginx"), ("openformulieren",)),
    "openklant": Component(("openklant",), ("openklant",)),
    "objecten": Component(("objecten",), ("objecten",)),
    "objecttypen": Component(("objecttypen",), ("objecttypen",)),
    "opennotificaties": Component(("notificaties", "opennotificaties"), ("opennotificaties", "notificaties")),
    "omc": Component(("omc",), ("omc",)),
    "openbeheer": Component(("openbeheer",), ("openbeheer",)),
    "referentielijsten": Component(("referentielijsten",), ("referentielijsten",)),
    "frankgateway": Component(("frankgateway",), ("frankgateway", "frank-gateway")),
    "grafana": Component(("grafana", "podiumd-logs"), ("grafana", "podiumd-grafana")),
    "mailpit": Component(("mailpit",), ("mailpit",)),
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
