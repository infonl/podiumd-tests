"""Environment profiles: one YAML file per environment under envs/.

A profile holds everything non-secret about an environment: the kube
context and namespace, the base URL per component, where each secret comes
from, and which tiers may run there (PLAN.md R7, R20).
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Literal
from typing import cast

import yaml

from podiumd_tests.components import COMPONENTS
from podiumd_tests.tiers import TIERS

ESTATES = ("minikube", "podiumd-infra", "externals")
# The repository: src/podiumd_tests/ is two levels below it.
REPO_ROOT = Path(__file__).resolve().parents[2]
# Secret sources that read the cluster; without kube access they cannot resolve.
CLUSTER_SECRET_SOURCES = ("k8s_secret", "pod_env", "zgw_jwt_secret")
SECRET_SOURCES = (*CLUSTER_SECRET_SOURCES, "keyvault", "dev_default")

AccessMode = Literal["direct", "host-header"]


class ProfileError(Exception):
    """A profile is missing or invalid."""


@dataclass(frozen=True)
class KubeSettings:
    """kubectl context and namespaces of an environment."""

    context: str
    namespace: str
    monitoring_namespace: str | None = None


@dataclass(frozen=True)
class ServiceRef:
    """A Kubernetes service by namespace and name."""

    namespace: str
    name: str


@dataclass(frozen=True)
class Access:
    """How the console reaches the component URLs.

    "direct": real DNS and TLS. "host-header": connect to the IP of the ingress
    service and send the URL's host as Host header (minikube, no /etc/hosts edits).
    """

    mode: AccessMode = "direct"
    ingress_service: ServiceRef | None = None


@dataclass(frozen=True)
class SecretSpec:
    """Where one secret comes from. An env var PODIUMD_TESTS_SECRET_<NAME> always wins."""

    name: str
    source: str
    options: dict[str, str] = field(default_factory=dict[str, str])

    @property
    def needs_cluster(self) -> bool:
        """True when resolving it reads the cluster."""
        return self.source in CLUSTER_SECRET_SOURCES


@dataclass(frozen=True)
class Profile:  # pylint: disable=too-many-instance-attributes  # mirrors the YAML schema
    """One environment, as read from envs/**/<name>.yaml."""

    name: str
    estate: str
    kube: KubeSettings
    urls: dict[str, str]
    allowed_tiers: tuple[str, ...]
    secrets: dict[str, SecretSpec]
    access: Access = Access()
    keyvault: str | None = None
    chart_version: str | None = None
    # Non-secret per-environment values, e.g. zgw_client_id.
    settings: dict[str, str] = field(default_factory=dict[str, str])
    path: Path | None = None


def default_envs_dir() -> Path:
    """envs/ in the repository root."""
    return REPO_ROOT / "envs"


def list_profiles(envs_dir: Path) -> dict[str, Path]:
    """Profile name -> file, for every *.yaml under envs_dir."""
    profiles: dict[str, Path] = {}
    for path in sorted(envs_dir.rglob("*.yaml")):
        if path.stem in profiles:
            msg = f"duplicate profile name {path.stem!r}: {profiles[path.stem]} and {path}"
            raise ProfileError(msg)
        profiles[path.stem] = path
    return profiles


def load_profile(name: str, envs_dir: Path) -> Profile:
    """Load a profile by name from envs_dir."""
    profiles = list_profiles(envs_dir)
    if name not in profiles:
        known = ", ".join(profiles) or "none"
        msg = f"no profile {name!r} under {envs_dir} (known: {known})"
        raise ProfileError(msg)
    path = profiles[name]
    raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    return parse_profile(raw, name=name, path=path)


def _mapping(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        msg = f"{where}: expected a mapping"
        raise ProfileError(msg)
    return {str(k): v for k, v in cast("dict[object, object]", value).items()}


def _optional_text(data: dict[str, object], key: str, where: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str | int | float):
        msg = f"{where}.{key}: expected a string"
        raise ProfileError(msg)
    return str(value)


def _required_text(data: dict[str, object], key: str, where: str) -> str:
    value = _optional_text(data, key, where)
    if value is None:
        msg = f"{where}: missing {key}"
        raise ProfileError(msg)
    return value


def _parse_urls(value: object, where: str) -> dict[str, str]:
    urls: dict[str, str] = {}
    for component, url in _mapping(value, where).items():
        if component not in COMPONENTS:
            msg = f"{where}: unknown component {component!r}"
            raise ProfileError(msg)
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            msg = f"{where}.{component}: expected an http(s) URL"
            raise ProfileError(msg)
        urls[component] = url.rstrip("/")
    return urls


def _parse_secrets(value: object, where: str) -> dict[str, SecretSpec]:
    secrets: dict[str, SecretSpec] = {}
    for name, spec in _mapping(value, where).items():
        spec_map = _mapping(spec, f"{where}.{name}")
        if len(spec_map) != 1:
            msg = f"{where}.{name}: expected exactly one source ({', '.join(SECRET_SOURCES)})"
            raise ProfileError(msg)
        source, options = next(iter(spec_map.items()))
        if source not in SECRET_SOURCES:
            msg = f"{where}.{name}: unknown source {source!r}"
            raise ProfileError(msg)
        option_map = {"value": str(options)} if source == "dev_default" else _mapping(options, f"{where}.{name}")
        secrets[name] = SecretSpec(name, source, {k: str(v) for k, v in option_map.items()})
    return secrets


def _parse_access(value: object, where: str) -> Access:
    if value is None:
        return Access()
    data = _mapping(value, where)
    mode = _optional_text(data, "mode", where) or "direct"
    if mode == "direct":
        return Access()
    if mode != "host-header":
        msg = f"{where}.mode: expected direct or host-header"
        raise ProfileError(msg)
    service = _mapping(data.get("ingress_service"), f"{where}.ingress_service")
    ref = ServiceRef(
        _required_text(service, "namespace", f"{where}.ingress_service"),
        _required_text(service, "name", f"{where}.ingress_service"),
    )
    return Access("host-header", ref)


def parse_profile(raw: object, *, name: str, path: Path | None = None) -> Profile:
    """Validate raw YAML data and turn it into a Profile."""
    where = str(path or name)
    data = _mapping(raw, where)
    estate = _required_text(data, "estate", where)
    if estate not in ESTATES:
        msg = f"{where}.estate: expected one of {', '.join(ESTATES)}"
        raise ProfileError(msg)
    kube_map = _mapping(data.get("kube"), f"{where}.kube")
    kube = KubeSettings(
        context=_required_text(kube_map, "context", f"{where}.kube"),
        namespace=_required_text(kube_map, "namespace", f"{where}.kube"),
        monitoring_namespace=_optional_text(kube_map, "monitoring_namespace", f"{where}.kube"),
    )
    tiers_raw = data.get("allowed_tiers")
    if not isinstance(tiers_raw, list) or not tiers_raw:
        msg = f"{where}: allowed_tiers must be a non-empty list"
        raise ProfileError(msg)
    tiers = tuple(str(t) for t in cast("list[object]", tiers_raw))
    unknown = [t for t in tiers if t not in TIERS]
    if unknown:
        msg = f"{where}.allowed_tiers: unknown tier(s) {', '.join(unknown)}"
        raise ProfileError(msg)
    secrets = _parse_secrets(data.get("secrets") or {}, f"{where}.secrets")
    if estate != "minikube" and any(s.source == "dev_default" for s in secrets.values()):
        msg = f"{where}.secrets: dev_default is only allowed for minikube"
        raise ProfileError(msg)
    return Profile(
        name=name,
        estate=estate,
        kube=kube,
        urls=_parse_urls(data.get("urls"), f"{where}.urls"),
        allowed_tiers=tiers,
        secrets=secrets,
        access=_parse_access(data.get("access"), f"{where}.access"),
        keyvault=_optional_text(data, "keyvault", where),
        chart_version=_optional_text(data, "chart_version", where),
        settings={str(k): str(v) for k, v in _mapping(data.get("settings") or {}, f"{where}.settings").items()},
        path=path,
    )
