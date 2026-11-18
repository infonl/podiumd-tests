"""Deployment hygiene of a workload, and its conformance to the PodiumD hosting standards (2025Q4, COMP numbers).

Tests gate only the baseline Pod Security Standard, pinned images, requests, disruption budgets, secrets from the
secrets store and probes of serving containers; most of PodiumD's charts do not meet the rest yet ("restricted",
limits, replicas), which `standards_report` lists per workload.
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import django_values
from podiumd_tests.kube import metadata_name
from podiumd_tests.kube import metadata_namespace
from podiumd_tests.process import ProcessError
from podiumd_tests.workloads import pod_containers

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Mapping
    from collections.abc import Sequence

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

# Capabilities the baseline level allows a container to add.
BASELINE_CAPABILITIES = frozenset(
    (
        "AUDIT_WRITE",
        "CHOWN",
        "DAC_OVERRIDE",
        "FOWNER",
        "FSETID",
        "KILL",
        "MKNOD",
        "NET_BIND_SERVICE",
        "SETFCAP",
        "SETGID",
        "SETPCAP",
        "SETUID",
        "SYS_CHROOT",
    )
)
# A disruption budget needs a second replica.
BUDGET_MIN_REPLICAS = 2


def baseline_violations(workload: JsonObject) -> list[str]:
    """Return what in the workload's pod template breaks the Pod Security Standard "baseline"."""
    name, pod = metadata_name(workload), section(section(section(workload, "spec"), "template"), "spec")
    found = [f"{name}: {key}" for key in ("hostNetwork", "hostPID", "hostIPC") if pod.get(key) is True]
    found += [
        f"{name}: hostPath volume {volume.get('name')}"
        for volume in entries(pod.get("volumes"))
        if "hostPath" in volume
    ]
    for container in pod_containers(workload, with_init=True):
        where = f"{name}/{container.get('name')}"
        context = section(container, "securityContext")
        if context.get("privileged") is True:
            found.append(f"{where}: privileged")
        added = set(strings(section(context, "capabilities").get("add"))) - BASELINE_CAPABILITIES
        if added:
            found.append(f"{where}: adds capabilities {sorted(added)}")
        found += [
            f"{where}: hostPort {port.get('hostPort')}"
            for port in entries(container.get("ports"))
            if port.get("hostPort")
        ]
    return found


def unpinned_images(workload: JsonObject) -> list[str]:
    """Images of the workload without a tag or digest, or tagged latest."""
    found: list[str] = []
    for container in pod_containers(workload, with_init=True):
        image = str(container.get("image") or "")
        if _is_unpinned(image):
            found.append(f"{metadata_name(workload)}/{container.get('name')}: {image}")
    return found


def _is_unpinned(image: str) -> bool:
    reference = image.rsplit("/", 1)[-1]
    return "@sha256:" not in image and (":" not in reference or reference.endswith(":latest"))


def missing_requests(workload: JsonObject) -> list[str]:
    """Containers of the workload without a CPU or a memory request: the scheduler cannot place them by size."""
    found: list[str] = []
    for container in pod_containers(workload, with_init=False):
        asked = section(section(container, "resources"), "requests")
        missing = [resource for resource in ("cpu", "memory") if not asked.get(resource)]
        if missing:
            found.append(f"{metadata_name(workload)}/{container.get('name')}: no {' or '.join(missing)} request")
    return found


def without_disruption_budget(workloads: Sequence[JsonObject], budgets: Sequence[JsonObject]) -> list[str]:
    """Names of the workloads with more than one replica whose pods no PodDisruptionBudget selects.

    A budget selects by its matchLabels only; matchExpressions are not evaluated.
    """
    replicated = [workload for workload in workloads if _is_replicated(workload)]
    return [metadata_name(workload) for workload in replicated if not _is_budgeted(workload, budgets)]


def _is_replicated(workload: JsonObject) -> bool:
    replicas = section(workload, "spec").get("replicas", 1)
    return isinstance(replicas, int) and replicas >= BUDGET_MIN_REPLICAS


def _is_budgeted(workload: JsonObject, budgets: Sequence[JsonObject]) -> bool:
    """Whether a PodDisruptionBudget in the workload's namespace selects its pods."""
    labels = section(section(section(section(workload, "spec"), "template"), "metadata"), "labels")
    return any(
        metadata_namespace(budget) == metadata_namespace(workload)
        and section(section(section(budget, "spec"), "selector"), "matchLabels").items() <= labels.items()
        for budget in budgets
    )


# An env var name that holds a credential (COMP012), unless it names a file, URL or setting about it.
SECRET_NAME = re.compile(r"PASSWORD|SECRET|TOKEN|API_?KEY|PRIVATE_KEY", re.IGNORECASE)
# etcd's INITIAL_CLUSTER_TOKEN names the cluster; etcd documents it as no secret.
NOT_A_SECRET = re.compile(
    r"_(FILE|PATH|URL|ENABLED|NAME|TYPE|HEADER|EXPIR\w*|LIFETIME|TTL|TIMEOUT)$|INITIAL_CLUSTER_TOKEN$", re.IGNORECASE
)


def literal_secrets(workload: JsonObject) -> list[str]:
    """Return the env vars of the workload's containers that set a credential by value, not from a Secret (COMP012)."""
    return [
        f"{metadata_name(workload)}/{container.get('name')}: {variable.get('name')}"
        for container in pod_containers(workload, with_init=True)
        for variable in entries(container.get("env"))
        if _is_literal_secret(variable)
    ]


def _is_literal_secret(variable: JsonObject) -> bool:
    name, value = str(variable.get("name") or ""), variable.get("value")
    if not SECRET_NAME.search(name) or NOT_A_SECRET.search(name) or not isinstance(value, str):
        return False
    return value.lower() not in {"", "true", "false"} and not value.isdigit()


def _is_selected_by(service: JsonObject, workload: JsonObject) -> bool:
    """Whether the Service sends traffic to the workload's pods: same namespace, its selector in their labels."""
    selector = section(section(service, "spec"), "selector")
    labels = section(section(section(section(workload, "spec"), "template"), "metadata"), "labels")
    return (
        metadata_namespace(service) == metadata_namespace(workload)
        and bool(selector)
        and selector.items() <= labels.items()
    )


def serving_containers(workload: JsonObject, services: Sequence[JsonObject]) -> list[JsonObject]:
    """Return the workload's containers that a Service in its namespace sends traffic to."""
    targets = {
        str(port.get("targetPort", port.get("port")))
        for service in services
        if _is_selected_by(service, workload)
        for port in entries(section(service, "spec").get("ports"))
    }
    return [
        container
        for container in pod_containers(workload, with_init=False)
        if any(
            {str(port.get("containerPort")), str(port.get("name"))} & targets
            for port in entries(container.get("ports"))
        )
    ]


def missing_probes(workload: JsonObject, services: Sequence[JsonObject]) -> list[str]:
    """Return the serving containers without a liveness or a readiness probe (COMP014.2)."""
    return [
        f"{metadata_name(workload)}/{container.get('name')}: no {probe}"
        for container in serving_containers(workload, services)
        for probe in ("livenessProbe", "readinessProbe")
        if probe not in container
    ]


def _pod(workload: JsonObject) -> JsonObject:
    return section(section(section(workload, "spec"), "template"), "spec")


def _is_true_for_all_containers(workload: JsonObject, check: Callable[[JsonObject, JsonObject], bool]) -> bool:
    containers = pod_containers(workload, with_init=False)
    return bool(containers) and all(check(container, _pod(workload)) for container in containers)


def _security(container: JsonObject, pod: JsonObject, key: str) -> object:
    return section(container, "securityContext").get(key, section(pod, "securityContext").get(key))


def _is_non_root(container: JsonObject, pod: JsonObject) -> bool:
    return _security(container, pod, "runAsNonRoot") is True or _security(container, pod, "runAsUser") not in {None, 0}


def _is_dropping_all(container: JsonObject, _pod_spec: JsonObject) -> bool:
    return "ALL" in strings(section(section(container, "securityContext"), "capabilities").get("drop"))


def _is_read_only(container: JsonObject, _pod_spec: JsonObject) -> bool:
    return section(container, "securityContext").get("readOnlyRootFilesystem") is True


def _has_memory_limit(container: JsonObject, _pod_spec: JsonObject) -> bool:
    return bool(section(section(container, "resources"), "limits").get("memory"))


def _has_startup_probe(container: JsonObject, _pod_spec: JsonObject) -> bool:
    return "startupProbe" in container


# The objects of the workloads' namespaces that the checks read, by kind.
type Objects = Mapping[str, Sequence[JsonObject]]
type Check = Callable[[JsonObject, Objects], bool]


def _has_no_literal_secret(workload: JsonObject, _objects: Objects) -> bool:
    return not literal_secrets(workload)


def _has_probes(workload: JsonObject, objects: Objects) -> bool:
    return not missing_probes(workload, objects["services"])


def _is_spread(workload: JsonObject, _objects: Objects) -> bool:
    pod = _pod(workload)
    return bool(pod.get("topologySpreadConstraints") or section(pod, "affinity").get("podAntiAffinity"))


def _has_autoscaler(workload: JsonObject, objects: Objects) -> bool:
    scaled = {section(section(scaler, "spec"), "scaleTargetRef").get("name") for scaler in objects["autoscalers"]}
    return metadata_name(workload) in scaled


def _has_budget(workload: JsonObject, objects: Objects) -> bool:
    return _is_budgeted(workload, objects["budgets"])


def _is_multiple(workload: JsonObject, _objects: Objects) -> bool:
    return _is_replicated(workload)


def _per_container(check: Callable[[JsonObject, JsonObject], bool]) -> Check:
    return lambda workload, _objects: _is_true_for_all_containers(workload, check)


# The report's checks per workload: (column, hosting standard, check).
STANDARDS: tuple[tuple[str, str, Check], ...] = (
    ("secrets", "COMP012", _has_no_literal_secret),
    ("probes", "COMP014.2", _has_probes),
    ("startup", "COMP014.2", _per_container(_has_startup_probe)),
    ("limits", "COMP020", _per_container(_has_memory_limit)),
    ("non-root", "COMP023", _per_container(_is_non_root)),
    ("drop ALL", "COMP023", _per_container(_is_dropping_all)),
    ("read-only fs", "COMP023", _per_container(_is_read_only)),
    ("2+ replicas", "COMP006.1", _is_multiple),
    ("PDB", "COMP014.4", _has_budget),
    ("spread", "COMP014.3", _is_spread),
    ("HPA", "COMP020", _has_autoscaler),
)


def conformance(workload: JsonObject, objects: Objects) -> dict[str, bool]:
    """Whether the workload meets each hosting standard check of STANDARDS, by column."""
    return {column: check(workload, objects) for column, _, check in STANDARDS}


def standards_report(workloads: Sequence[JsonObject], objects: Objects, title: str) -> str:
    """Return the Markdown matrix of workloads against the hosting standard checks, with a count per check."""
    rows = {f"{item.get('kind', '')} {metadata_name(item)}": conformance(item, objects) for item in workloads}
    columns = [column for column, _, _ in STANDARDS]
    counts: list[str] = []
    for column, standard, _ in STANDARDS:
        conforming = sum(row[column] for row in rows.values())
        counts.append(f"| {column} | {standard} | {conforming} / {len(rows)} |")
    matrix = [f"| Workload | {' | '.join(columns)} |", f"| --- |{' --- |' * len(columns)}"]
    for name, row in sorted(rows.items()):
        cells = ["yes" if row[column] else "**no**" for column in columns]
        matrix.append(f"| {name} | {' | '.join(cells)} |")
    head = ["| Check | Standard | Conforming |", "| --- | --- | --- |"]
    return "\n".join([f"# {title}", "", *head, *counts, "", *matrix, ""])


# Stand-ins some estates run for SSC's services and external registers (mail catcher, BRP and BAG mocks, an
# in-cluster PostgreSQL for Azure's): no PodiumD component, so no hosting standard applies.
STAND_INS = frozenset(("mailpit", "brp-personen-mock", "bag-mock", "postgres"))
# Database time zone names that mean UTC (COMP004).
UTC_NAMES = frozenset(("UTC", "Etc/UTC", "GMT", "Etc/GMT", "Zulu"))
_EXEC_KINDS = {"Deployment": "deploy", "StatefulSet": "sts"}


def is_hosted_component(workload: JsonObject) -> bool:
    """Whether the hosting standards apply to the workload as delivered: no stand-in, not made by an operator.

    An operator decides its workloads' probes and security (ECK leaves out Elasticsearch's liveness probe on purpose).
    """
    return metadata_name(workload) not in STAND_INS and not entries(
        section(workload, "metadata").get("ownerReferences")
    )


def hosting_scope(env: Environment, namespaces: Sequence[str] | None = None) -> tuple[list[JsonObject], Objects]:
    """Return the workloads of the namespaces (default all of the environment's) and the objects the checks read."""
    objects: Objects = {
        "services": env.items("services", namespaces),
        "budgets": env.items("poddisruptionbudgets", namespaces),
        "autoscalers": env.items("horizontalpodautoscalers", namespaces),
    }
    return cast("list[JsonObject]", env.workloads(namespaces)), objects


def clock_offset(env: Environment, workload: JsonObject) -> str | None:
    """Return the UTC offset (date +%z) of the workload's first container; None when it cannot run date."""
    kind = _EXEC_KINDS.get(str(workload.get("kind")))
    containers = pod_containers(workload, with_init=False)
    if kind is None or not containers:
        return None
    container = str(containers[0].get("name"))
    try:
        output = env.kube.run("exec", f"{kind}/{metadata_name(workload)}", "-c", container, "--", "date", "+%z")
    except (KubeError, ProcessError):
        return None
    return output.strip() or None


def database_time_zone(env: Environment, component: str = "openzaak") -> str:
    """Return the PostgreSQL time zone a new session of the component starts with (its reset value, not Django's)."""
    code = (
        "from django.db import connection\n"
        "with connection.cursor() as cursor:\n"
        "    cursor.execute(\"SELECT reset_val FROM pg_settings WHERE name = 'TimeZone'\")\n"
        "    print('PTEST_VALUE=' + cursor.fetchone()[0])\n"
    )
    return django_values(env.kube.exec_django_shell(env.deployment_for(component), code))[0]


def cluster_names(env: Environment, component: str) -> list[str]:
    """Return the base URLs of the Service of a component's main Deployment by each cluster DNS name.

    The short name, with the namespace and fully qualified; the hosting standards ask each to work. None for a
    component without a Deployment of its own (Keycloak's operator runs a StatefulSet) or a Service.
    """
    namespace = env.profile.kube.namespace
    try:
        wanted = env.deployment_for(component)
    except KubeError:
        return []
    deployments = [item for item in env.items("deployments", [namespace]) if metadata_name(item) == wanted]
    services = [
        item for item in env.items("services", [namespace]) for found in deployments if _is_selected_by(item, found)
    ]
    if not services:
        return []
    name, port = metadata_name(services[0]), _http_port(services[0])
    hosts = (name, f"{name}.{namespace}", f"{name}.{namespace}.svc.cluster.local")
    return [f"http://{host}:{port}/" for host in hosts]


def _http_port(service: JsonObject) -> object:
    ports = entries(section(service, "spec").get("ports"))
    named = [port for port in ports if port.get("name") in {"http", "web"}]
    return (named or ports or [{}])[0].get("port", 80)
