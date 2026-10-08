"""Read-only preflight checks: can a run against this environment work? (PLAN.md R17, §8b)

Each check gives ok, warn, fail or skip (a check it depends on failed).
Any fail means exit code 2.
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

import requests

from podiumd_tests.credentials import SecretError
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import context_names
from podiumd_tests.lock import lease_holder
from podiumd_tests.responses import get_root
from podiumd_tests.responses import is_server_error
from podiumd_tests.responses import url_host
from podiumd_tests.workloads import unready_workloads

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
        hint = "add it with `az aks get-credentials` or `minikube start`; without it cluster tests skip"
        return [Check("kube context", no_access, f"{context} not in kubeconfig", hint)]
    checks = [Check("kube context", "ok", context)]
    try:
        env.kube.api_reachable()
    except KubeError as exc:
        checks.append(Check("kube API", no_access, str(exc), "cluster stopped or deleted? (scheduled shutdown)"))
        return checks
    checks.append(Check("kube API", "ok", "readyz"))
    checks.append(_lock(env))
    for namespace in env.namespaces:
        try:
            env.kube.run("get", "namespace", namespace, "-o", "name")
        except KubeError as exc:
            checks.append(Check(f"namespace {namespace}", "fail", str(exc)))
            continue
        checks.append(Check(f"namespace {namespace}", "ok"))
        checks.append(_workloads(env, namespace))
    return checks


def _lock(env: Environment) -> Check:
    try:
        current = lease_holder(env.kube)
    except KubeError as exc:
        return Check("lock", "warn", f"cannot read the lease: {exc}", "writing runs need RBAC on leases")
    if current:
        return Check("lock", "warn", f"held by {current}", "writing runs refuse until it is free")
    return Check("lock", "ok", "free")


def _workloads(env: Environment, namespace: str) -> Check:
    items = env.workloads([namespace])
    not_ready = unready_workloads(items)
    if not_ready:
        return Check(f"workloads {namespace}", "warn", "not ready: " + ", ".join(not_ready))
    return Check(f"workloads {namespace}", "ok", f"{len(items)} ready")


def _getaddrinfo(host: str) -> None:
    socket.getaddrinfo(host, None)


def resolve_hosts(
    hosts: Iterable[str], resolve: Resolver = _getaddrinfo, timeout: float = DNS_TIMEOUT
) -> dict[str, str]:
    """Look up all hosts in parallel; the error per host, "" when it resolved.

    The system resolver has no timeout and can take 10-20 s per unknown host;
    daemon threads let doctor stop at the deadline without keeping the process alive.
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
        response = get_root(session, url, HTTP_TIMEOUT)
    except requests.exceptions.SSLError as exc:
        return Check(name, "fail", f"{url}: TLS error: {exc}")
    except requests.exceptions.ConnectTimeout:
        return Check(name, "fail", f"{url}: no connection within {HTTP_TIMEOUT[0]}s", DOWN_HINT)
    except requests.exceptions.RequestException as exc:
        return Check(name, "fail", f"{url}: {type(exc).__name__}")
    status: Status = "fail" if is_server_error(response) else "ok"
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
        dns_errors = resolve_hosts((url_host(u) for _, u in urls), resolve)
    checks: dict[str, Check] = {}
    reachable: list[tuple[str, str]] = []
    for component, url in urls:
        error = dns_errors.get(url_host(url), "")
        if error:
            checks[component] = Check(f"url {component}", "fail", f"{url}: {error}", DOWN_HINT)
        else:
            reachable.append((component, url))
    if reachable:
        with ThreadPoolExecutor(max_workers=min(len(reachable), 16)) as pool:
            futures = {c: pool.submit(_url_check, session, c, u) for c, u in reachable}
            checks.update({c: f.result() for c, f in futures.items()})
    return [checks[component] for component, _ in urls]


def _secrets(env: Environment, *, cluster_ok: bool) -> list[Check]:
    checks: list[Check] = []
    for name in env.credentials.names:
        if not cluster_ok and env.profile.secrets[name].needs_cluster:
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
