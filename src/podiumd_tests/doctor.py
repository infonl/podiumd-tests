"""Preflight: can a run against this environment work right now? (PLAN.md R17, §8b)

Read-only. Each check gives ok, warn, fail or skip (an earlier check it
depends on failed). Any fail means exit code 2.
"""

from __future__ import annotations

import shutil
import socket
import threading
import time

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Literal
from typing import cast
from urllib.parse import urlsplit

import requests

from podiumd_tests.credentials import SecretError
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import context_names
from podiumd_tests.kube import metadata_name

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterable

    from podiumd_tests.environment import Environment

    Resolver = Callable[[str], object]

Status = Literal["ok", "warn", "fail", "skip"]
DNS_TIMEOUT = 5.0
HTTP_TIMEOUT = (5, 10)  # connect, read
DOWN_HINT = "environment down or DNS removed? (scheduled shutdown)"
SYMBOLS: dict[Status, str] = {"ok": "✔", "warn": "!", "fail": "✘", "skip": "-"}


@dataclass(frozen=True)
class Check:
    """Result of one preflight check."""

    name: str
    status: Status
    detail: str = ""
    hint: str = ""


def _tools(env: Environment, which: Callable[[str], str | None]) -> list[Check]:
    needed = ["kubectl"]
    if any(s.source == "keyvault" for s in env.profile.secrets.values()):
        needed.append("az")
    return [
        Check(f"tool {tool}", "ok", path) if (path := which(tool)) else Check(f"tool {tool}", "fail", "not on PATH")
        for tool in needed
    ]


def _cluster(env: Environment) -> list[Check]:
    # In direct mode the URLs work without the cluster: no access only skips the cluster tests.
    no_access: Status = "fail" if env.profile.access.mode == "host-header" else "warn"
    context = env.profile.kube.context
    try:
        known = context_names(env.kube.runner)
    except KubeError as exc:
        return [Check("kube context", "fail", str(exc))]
    if context not in known:
        hint = "e.g. az aks get-credentials / minikube start; without it cluster tests skip"
        return [Check("kube context", no_access, f"{context} not in kubeconfig", hint)]
    checks = [Check("kube context", "ok", context)]
    try:
        env.kube.api_reachable()
    except KubeError as exc:
        checks.append(Check("kube API", no_access, str(exc), "cluster stopped or deleted? (scheduled shutdown)"))
        return checks
    checks.append(Check("kube API", "ok", "readyz"))
    for namespace in env.namespaces:
        try:
            env.kube.run("get", "namespace", namespace, "-o", "name")
        except KubeError as exc:
            checks.append(Check(f"namespace {namespace}", "fail", str(exc)))
            continue
        checks.append(Check(f"namespace {namespace}", "ok"))
        checks.append(_deployments(env, namespace))
    return checks


def _deployments(env: Environment, namespace: str) -> Check:
    not_ready: list[str] = []
    items = env.kube.items("deployments", namespace=namespace)
    for item in items:
        status = cast("dict[str, object]", item.get("status") or {})
        spec = cast("dict[str, object]", item.get("spec") or {})
        wanted = int(str(spec.get("replicas", 1)))
        ready = int(str(status.get("readyReplicas", 0)))
        if ready < wanted:
            not_ready.append(f"{metadata_name(item)} {ready}/{wanted}")
    if not_ready:
        return Check(f"deployments {namespace}", "warn", "not ready: " + ", ".join(not_ready))
    return Check(f"deployments {namespace}", "ok", f"{len(items)} ready")


def _getaddrinfo(host: str) -> None:
    socket.getaddrinfo(host, None)


def resolve_hosts(
    hosts: Iterable[str], resolve: Resolver = _getaddrinfo, timeout: float = DNS_TIMEOUT
) -> dict[str, str]:
    """Look up all hosts in parallel; the error per host, "" when it resolved.

    The system resolver has no timeout of its own and can take 10-20 s per
    unknown host. Daemon threads let doctor stop waiting at the deadline,
    and do not keep the process alive afterwards.
    """
    results: dict[str, str] = {}

    def lookup(host: str) -> None:
        try:
            resolve(host)
        except OSError as exc:
            results[host] = f"DNS lookup failed: {exc}"
        else:
            results[host] = ""

    unique = set(hosts)
    threads = [threading.Thread(target=lookup, args=(host,), daemon=True) for host in unique]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    done = dict(results)
    return {host: done.get(host, f"DNS lookup gave no answer within {timeout:g}s") for host in unique}


def _url_check(session: requests.Session, component: str, url: str) -> Check:
    name = f"url {component}"
    try:
        response = session.get(url + "/", allow_redirects=False, timeout=HTTP_TIMEOUT)
    except requests.exceptions.SSLError as exc:
        return Check(name, "fail", f"{url}: TLS error: {exc}")
    except requests.exceptions.ConnectTimeout:
        return Check(name, "fail", f"{url}: no connection within {HTTP_TIMEOUT[0]}s", DOWN_HINT)
    except requests.exceptions.RequestException as exc:
        return Check(name, "fail", f"{url}: {type(exc).__name__}")
    status: Status = "fail" if response.status_code >= 500 else "ok"
    return Check(name, status, f"{url}: HTTP {response.status_code}")


def _urls(env: Environment, resolve: Resolver) -> list[Check]:
    try:
        session = env.session()
    except KubeError as exc:
        return [Check("ingress IP", "fail", str(exc))]
    urls = sorted(env.profile.urls.items())
    # In host-header mode the requests go to the ingress IP; the hosts need not resolve.
    dns_errors: dict[str, str] = {}
    if env.profile.access.mode == "direct":
        dns_errors = resolve_hosts((urlsplit(u).hostname or "" for _, u in urls), resolve)
    checks: dict[str, Check] = {}
    reachable: list[tuple[str, str]] = []
    for component, url in urls:
        error = dns_errors.get(urlsplit(url).hostname or "", "")
        if error:
            checks[component] = Check(f"url {component}", "fail", f"{url}: {error}", DOWN_HINT)
        else:
            reachable.append((component, url))
    if reachable:
        with ThreadPoolExecutor(max_workers=min(len(reachable), 16)) as pool:
            futures = {c: pool.submit(_url_check, session, c, u) for c, u in reachable}
            checks.update({c: f.result() for c, f in futures.items()})
    return [checks[component] for component, _ in urls]


CLUSTER_SOURCES = {"k8s_secret", "pod_env", "zgw_jwt_secret"}


def _secrets(env: Environment, *, cluster_ok: bool) -> list[Check]:
    checks: list[Check] = []
    for name in env.credentials.names:
        if not cluster_ok and env.profile.secrets[name].source in CLUSTER_SOURCES:
            checks.append(Check(f"secret {name}", "skip", "no cluster"))
            continue
        try:
            env.credentials.get(name)
        except SecretError as exc:
            checks.append(Check(f"secret {name}", "fail", str(exc)))
        else:
            checks.append(Check(f"secret {name}", "ok", env.profile.secrets[name].source))
    return checks


def _capabilities(env: Environment) -> Check:
    caps = env.capabilities
    absent = sorted(set(caps.reasons))
    detail = "present: " + (", ".join(sorted(caps.present)) or "none")
    if absent:
        detail += "; absent: " + ", ".join(absent)
    return Check("capabilities", "ok", detail)


def run_checks(
    env: Environment, which: Callable[[str], str | None] = shutil.which, resolve: Resolver = _getaddrinfo
) -> list[Check]:
    """Run all preflight checks; dependent checks are skipped after a failure."""
    checks = [Check("profile", "ok", str(env.profile.path or env.profile.name))]
    checks += _tools(env, which)
    if any(c.status == "fail" and c.name == "tool kubectl" for c in checks):
        return [*checks, Check("cluster", "skip", "kubectl missing")]
    cluster = _cluster(env)
    checks += cluster
    cluster_ok = all(c.status == "ok" for c in cluster if c.name in {"kube context", "kube API"})
    checks += (
        _urls(env, resolve)
        if cluster_ok or env.profile.access.mode == "direct"
        else [Check("urls", "skip", "no cluster")]
    )
    checks += _secrets(env, cluster_ok=cluster_ok)
    # Without cluster access the capabilities come from the profile alone (and "cluster" is absent).
    checks.append(_capabilities(env))
    return [Check(c.name, c.status, env.redactor.redact(c.detail), c.hint) for c in checks]


def failed(checks: list[Check]) -> bool:
    """True when any check failed."""
    return any(c.status == "fail" for c in checks)


def format_checks(checks: list[Check]) -> str:
    """Checklist text for the terminal, with hints for failures and warnings."""
    width = max((len(c.name) for c in checks), default=0)
    lines: list[str] = []
    for c in checks:
        line = f"{SYMBOLS[c.status]} {c.name.ljust(width)}  {c.detail}".rstrip()
        if c.hint and c.status in {"fail", "warn"}:
            line += f"\n  {' ' * width}  hint: {c.hint}"
        lines.append(line)
    return "\n".join(lines)
