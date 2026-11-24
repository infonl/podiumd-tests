"""An estate profile: the settings of an environment that decide how a PodiumD upgrade goes there.

Read-only: kubectl, and Keycloak's admin API where the profile's credentials resolve. It holds no secrets, hosts,
URLs or user names. A value that cannot be read is "unknown", with the reason under its section's `reasons`;
`reasons` also says where a value came from when it was not read directly.
"""

from __future__ import annotations

import json
import re

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import cast

import requests
import yaml

from podiumd_tests import workloads
from podiumd_tests.auth.keycloak import TokenError
from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.auth.master_otp import CONDITIONAL
from podiumd_tests.auth.master_otp import DISABLED
from podiumd_tests.auth.master_otp import OPERATOR
from podiumd_tests.auth.master_otp import REQUIRED
from podiumd_tests.auth.master_otp import direct_grant_flow
from podiumd_tests.auth.master_otp import otp_requirement
from podiumd_tests.cilium import CILIUM
from podiumd_tests.cilium import detect_network
from podiumd_tests.config import ProfileError
from podiumd_tests.config import choice
from podiumd_tests.config import mapping
from podiumd_tests.config import required_text
from podiumd_tests.credentials import SecretError
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import metadata_labels
from podiumd_tests.kube import metadata_namespace
from podiumd_tests.process import ProcessError
from podiumd_tests.responses import UnexpectedStatusError
from podiumd_tests.wait import parse_duration

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Sequence
    from pathlib import Path

    from podiumd_tests.auth.keycloak_admin import KeycloakAdmin
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.kube import Kube

type Section = dict[str, object]

UNKNOWN = "unknown"
PRESENT = "present"
ABSENT = "absent"
SOURCES = ("kubectl", "keycloak-admin", "manual")
# The values each keycloak_master field may have.
MASTER_VALUES = {
    "direct_grant_otp": (REQUIRED, CONDITIONAL, DISABLED, UNKNOWN),
    "operator_client": (PRESENT, ABSENT, UNKNOWN),
}
ADMIN_CREDENTIALS = ("keycloak_admin_username", "keycloak_admin_password")
# A Job that runs this long without completing or failing hangs.
HANGING = timedelta(minutes=30)
LOG_TIMEOUT = 180
CHART_LABEL = re.compile(r"(?P<name>.+?)-(?P<version>v?\d+\.\d+.*)")
# Keycloak log lines: the operator's login without its client; a password grant that OTP refused with an error.
NOT_FOUND = ("CLIENT_LOGIN_ERROR", "client_not_found", OPERATOR)
OTP_FAILURE = ("AuthenticationFlowException", "direct-grant-validate-otp")
OTP_POLICY = ("type", "algorithm", "digits", "period")
# Errors of a read that make its value unknown.
READ_ERRORS = (KubeError, LookupError, SecretError, TokenError, UnexpectedStatusError, requests.RequestException)
HOST = re.compile(r"https?://\S+|\b(?:[\w-]+\.){2,}[a-z]{2,}(?::\d+)?\b|\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")
# A kubectl command line in an error message, up to its error.
COMMAND = re.compile(r"kubectl [^:]*: ")


def reason(error: Exception) -> str:
    """Return the error, or the command error that caused it, without command line, URLs, hosts or addresses."""
    cause: BaseException = error
    while not isinstance(cause, ProcessError) and cause.__cause__ is not None:
        cause = cause.__cause__
    text = cause.message.removeprefix(f"{cause.command}: ") if isinstance(cause, ProcessError) else str(error)
    return scrub(text)


def scrub(text: str) -> str:
    """Return text without kubectl command lines, URLs, host names or addresses."""
    return HOST.sub("<host>", COMMAND.sub("", text))


def mark_unknown(found: Section, field: str, why: str) -> None:
    """Set the field to UNKNOWN and record why."""
    found[field] = UNKNOWN
    cast("Section", found.setdefault("reasons", {}))[field] = why


def _put(found: Section, field: str, read: Callable[[], object]) -> None:
    """Set the field to what read returns, or to UNKNOWN when it fails."""
    try:
        found[field] = read()
    except READ_ERRORS as exc:
        mark_unknown(found, field, reason(exc))


def _known[ValueT](value: ValueT | None, missing: str) -> ValueT:
    if value is None:
        raise LookupError(missing)
    return value


def export(env: Environment, since: str, now: datetime | None = None) -> Section:
    """Return the environment's estate profile; KubeError when its cluster does not answer."""
    now = now or datetime.now(tz=UTC)
    env.kube.api_reachable()
    keycloak, statefulset = _keycloak(env)
    signals = _signals(env, statefulset, since, now)
    master, source = _keycloak_master(env, signals)
    return {
        "estate": env.profile.estate,
        "env": env.profile.name,
        "exported_at": now.isoformat(timespec="seconds"),
        "source": source,
        "chart": _chart(env),
        "cluster": _cluster(env.kube),
        "keycloak": keycloak,
        "keycloak_master": master,
        "signals": signals,
    }


def component_charts(items: Sequence[JsonObject]) -> dict[str, str]:
    """Return chart name -> version from the workloads' helm.sh/chart labels."""
    found: dict[str, str] = {}
    for item in items:
        matched = CHART_LABEL.fullmatch(str(metadata_labels(item).get("helm.sh/chart", "")))
        if matched:
            found[matched["name"]] = matched["version"]
    return dict(sorted(found.items()))


def _chart(env: Environment) -> Section:
    chart: Section = {}
    _put(chart, "podiumd", lambda: _known(workloads.chart_version(env), "no podiumd ConfigMap with a version label"))
    _put(chart, "components", lambda: component_charts(env.workloads()))
    return chart


def _cluster(kube: Kube) -> Section:
    cluster: Section = {}
    _put(cluster, "kubernetes", lambda: _server_version(kube))
    try:
        nodes = kube.items("nodes")
    except KubeError as exc:
        mark_unknown(cluster, "nodes", reason(exc))
        mark_unknown(cluster, "node_pools", reason(exc))
    else:
        cluster["nodes"] = len(nodes)
        _put(cluster, "node_pools", lambda: _known(node_pools(nodes), "no agentpool label on the nodes"))
    present, reasons = detect_network(kube)
    if CILIUM in present:
        cluster["cni"] = CILIUM
    else:
        mark_unknown(cluster, "cni", scrub(reasons[CILIUM]))
    return cluster


def _server_version(kube: Kube) -> str:
    printed = cast("JsonObject", json.loads(kube.run("version", "-o", "json")))
    return str(_known(section(printed, "serverVersion").get("gitVersion"), "no serverVersion"))


def node_pools(nodes: Sequence[JsonObject]) -> list[str] | None:
    """Return the AKS node pool names of the nodes; None when no node has a pool label."""
    labels = [metadata_labels(node) for node in nodes]
    pools = {str(found.get("kubernetes.azure.com/agentpool") or found.get("agentpool") or "") for found in labels}
    return sorted(pools - {""}) or None


def _keycloak(env: Environment) -> tuple[Section, JsonObject | None]:
    """Return the keycloak section and Keycloak's StatefulSet, if readable."""
    keycloak: Section = {}
    try:
        statefulset = _known(keycloak_statefulset(env.items("statefulsets")), "no Keycloak StatefulSet")
    except READ_ERRORS as exc:
        mark_unknown(keycloak, "version", reason(exc))
        mark_unknown(keycloak, "replicas", reason(exc))
        return keycloak, None
    keycloak["replicas"] = int(str(section(statefulset, "spec").get("replicas", 1)))
    image = workloads.image_version(statefulset)
    if image:
        keycloak["version"] = ".".join(map(str, image))
    else:
        _put(keycloak, "version", lambda: _operator_version(env))
        if keycloak["version"] != UNKNOWN:
            keycloak["reasons"] = {"version": "image pinned by digest: the keycloak-operator Deployment's version"}
    return keycloak, statefulset


def keycloak_statefulset(statefulsets: Sequence[JsonObject]) -> JsonObject | None:
    """Return the StatefulSet the Keycloak operator runs Keycloak in."""
    return next(
        (
            item
            for item in statefulsets
            if metadata_labels(item).get("app.kubernetes.io/managed-by") == "keycloak-operator"
        ),
        None,
    )


def _operator_version(env: Environment) -> str:
    operators = [
        item
        for item in env.items("deployments")
        if metadata_labels(item).get("app.kubernetes.io/name") == "keycloak-operator"
    ]
    version = metadata_labels(operators[0]).get("app.kubernetes.io/version") if operators else None
    return str(_known(version, "image pinned by digest and no keycloak-operator Deployment with a version label"))


def _signals(env: Environment, statefulset: JsonObject | None, since: str, now: datetime) -> Section:
    signals: Section = {"since": since}
    if statefulset is None:
        mark_unknown(signals, "operator_client_not_found", "no Keycloak StatefulSet")
        mark_unknown(signals, "otp_flow_errors", "no Keycloak StatefulSet")
    else:
        try:
            log = _keycloak_log(env.kube, statefulset, since)
        except KubeError as exc:
            mark_unknown(signals, "operator_client_not_found", reason(exc))
            mark_unknown(signals, "otp_flow_errors", reason(exc))
        else:
            signals.update(log_signals(log))
    try:
        jobs = [job for job in env.items("jobs") if workloads.is_keycloak_setup(job)]
    except KubeError as exc:
        mark_unknown(signals, "keycloak_jobs_failed", reason(exc))
        mark_unknown(signals, "keycloak_jobs_hanging", reason(exc))
        return signals
    try:
        keycloaks = env.items(workloads.KEYCLOAKS)
    except KubeError:  # read-only access without the operator's CRs: its expected update Jobs count as failed
        keycloaks = []
    signals["keycloak_jobs_failed"] = workloads.failed_jobs(jobs, keycloaks)
    signals["keycloak_jobs_hanging"] = workloads.hanging_jobs(jobs, now - HANGING)
    return signals


def _keycloak_log(kube: Kube, statefulset: JsonObject, since: str) -> str:
    """Return what every Keycloak pod logged in the last `since`."""
    selector = section(section(section(statefulset, "spec"), "selector"), "matchLabels")
    labels = ",".join(f"{key}={value}" for key, value in selector.items())
    seconds = int(parse_duration(since).total_seconds())
    args = ("logs", "-l", labels, f"--since={seconds}s", "--tail=-1", "--max-log-requests=20")
    return kube.run(*args, namespace=metadata_namespace(statefulset), timeout=LOG_TIMEOUT)


def log_signals(log: str) -> dict[str, int]:
    """Count the operator's client_not_found logins and the direct grant's OTP failures in a Keycloak log."""
    lines = log.splitlines()
    return {
        "operator_client_not_found": sum(_has_all(line, NOT_FOUND) for line in lines),
        "otp_flow_errors": sum(_has_all(line, OTP_FAILURE) for line in lines),
    }


def _has_all(line: str, parts: tuple[str, ...]) -> bool:
    return all(part in line for part in parts)


def _keycloak_master(env: Environment, signals: Section) -> tuple[Section, str]:
    """Return the keycloak_master section and the profile's source."""
    master: Section = {}
    admin = _master_admin(env, signals)
    if isinstance(admin, str):
        _from_signals(master, signals, admin)
        return master, "kubectl"
    _put(master, "direct_grant_otp", lambda: otp_requirement(admin.flow_executions(direct_grant_flow(admin))))
    _put(master, "operator_client", lambda: PRESENT if admin.client(OPERATOR) else ABSENT)
    _put(master, "required_actions", lambda: required_actions(admin.realm_role_users("admin")))
    _put(master, "otp_policy", lambda: otp_policy(admin.representation()))
    return master, "keycloak-admin"


def _master_admin(env: Environment, signals: Section) -> KeycloakAdmin | str:
    """Return a master admin client, or why there is none."""
    if not all(env.credentials.is_configured(name) for name in ADMIN_CREDENTIALS):
        return "no Keycloak admin credentials in the profile"
    if _count(signals, "otp_flow_errors"):
        return "master requires OTP on password grants (Keycloak log), so no admin login"
    try:
        return for_environment(env, "master")
    except READ_ERRORS as exc:
        return f"Keycloak admin login failed: {reason(exc)}"


def _count(signals: Section, field: str) -> int:
    found = signals.get(field)
    return found if isinstance(found, int) else 0


def _from_signals(master: Section, signals: Section, why: str) -> None:
    """Derive keycloak_master from the Keycloak log where it shows; the rest is unknown for `why`."""
    since = signals["since"]
    not_found = _count(signals, "operator_client_not_found")
    if not_found:
        master["operator_client"] = ABSENT
        logged = f"{not_found} client_not_found logins of {OPERATOR} in {since} (Keycloak log)"
        cast("Section", master.setdefault("reasons", {}))["operator_client"] = f"{logged}; {why}"
    else:
        mark_unknown(master, "operator_client", why)
    failures = _count(signals, "otp_flow_errors")
    if failures:
        master["direct_grant_otp"] = REQUIRED
        logged = f"{failures} OTP failures of password grants in {since} (Keycloak log)"
        cast("Section", master.setdefault("reasons", {}))["direct_grant_otp"] = f"{logged}; {why}"
    else:
        mark_unknown(master, "direct_grant_otp", why)
    mark_unknown(master, "required_actions", why)
    mark_unknown(master, "otp_policy", why)


def required_actions(users: Sequence[JsonObject]) -> dict[str, int]:
    """Return required action -> how many of the users have it."""
    found: dict[str, int] = {}
    for user in users:
        for action in strings(user.get("requiredActions")):
            found[action] = found.get(action, 0) + 1
    return dict(sorted(found.items()))


def otp_policy(realm: JsonObject) -> dict[str, object]:
    """Return the realm's OTP policy: type, algorithm, digits, period."""
    return {name: realm.get(f"otpPolicy{name.capitalize()}") for name in OTP_POLICY}


def dump(profile: Section) -> str:
    """Return the profile as YAML."""
    return yaml.safe_dump(profile, sort_keys=False, allow_unicode=True)


def load(path: Path) -> Section:
    """Read and validate a profile file; ProfileError when it is unreadable or invalid."""
    try:
        raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        msg = f"{path}: {exc}"
        raise ProfileError(msg) from exc
    return validate(raw, str(path))


def validate(raw: object, where: str) -> Section:
    """Return the profile when its estate, source and keycloak_master values are valid; ProfileError otherwise."""
    profile = mapping(raw, where)
    required_text(profile, "estate", where)
    choice(profile.get("source"), SOURCES, f"{where}.source")
    master = mapping(profile.get("keycloak_master", {}), f"{where}.keycloak_master")
    for field, allowed in MASTER_VALUES.items():
        choice(master.get(field, UNKNOWN), allowed, f"{where}.keycloak_master.{field}")
    return profile


def master_value(profile: JsonObject, field: str) -> str:
    """Return a keycloak_master field of a validated profile; UNKNOWN when absent."""
    return str(section(profile, "keycloak_master").get(field, UNKNOWN))
