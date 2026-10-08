"""The environment lock: one writing run at a time, from a console, a pipeline or another agent.

Two locks, both taken when configured or reachable:
- a Lease podiumd-tests-lock in the environment's namespace, so runs on different machines see
  each other; it names its holder and expires after settings.lock_lease_seconds (default 3 h),
  after which the next run takes it over;
- the lock file of settings.lock_file, shared with other agents on the same machine: one line
  "<who> <what> <ISO start time>", taken exclusively (O_EXCL).
"""

from __future__ import annotations

import getpass
import json
import os
import socket

from contextlib import contextmanager
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from podiumd_tests.capabilities import CLUSTER
from podiumd_tests.json_data import section
from podiumd_tests.kube import KubeError

if TYPE_CHECKING:
    from collections.abc import Generator

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.kube import Kube

HOLDER = "podiumd-tests"
LEASE = "podiumd-tests-lock"
LEASE_SECONDS = 3 * 3600


class LockBusyError(Exception):
    """Another run holds the lock; the message names it."""


def holder(what: str) -> str:
    """Who takes the lock and for what, e.g. "podiumd-tests kees@laptop run full kees00"."""
    return f"{HOLDER} {getpass.getuser()}@{socket.gethostname()} {what}"


def _lease(kube: Kube, who: str, seconds: int, now: datetime) -> dict[str, object]:
    return {
        "apiVersion": "coordination.k8s.io/v1",
        "kind": "Lease",
        "metadata": {"name": LEASE, "labels": {"app.kubernetes.io/managed-by": HOLDER}, "namespace": kube.namespace},
        "spec": {
            "holderIdentity": who,
            "acquireTime": now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "leaseDurationSeconds": seconds,
        },
    }


def lease_holder(kube: Kube, now: datetime | None = None) -> str | None:
    """The holder and start of the unexpired lease, or None when no run holds it."""
    found = kube.get_optional("lease", LEASE)
    if found is None:
        return None
    spec: JsonObject = section(found, "spec")
    started = datetime.fromisoformat(str(spec.get("acquireTime")))
    expires = started + timedelta(seconds=int(str(spec.get("leaseDurationSeconds") or 0)))
    if expires < (now or datetime.now(tz=UTC)):
        return None
    return f"{spec.get('holderIdentity')} since {started:%Y-%m-%d %H:%M}Z"


def take_lease(kube: Kube, who: str, seconds: int) -> None:
    """Take the lease for `seconds`; LockBusyError while another run holds it unexpired."""
    now = datetime.now(tz=UTC)
    current = lease_holder(kube, now)
    if current:
        msg = f"lease {LEASE} in {kube.namespace} is held by {current}; wait or ask its holder"
        raise LockBusyError(msg)
    kube.delete("lease", LEASE)  # an expired one
    try:
        kube.run("create", "-f", "-", stdin=json.dumps(_lease(kube, who, seconds, now)))
    except KubeError as exc:  # another run created it in between
        msg = f"lease {LEASE} in {kube.namespace} was just taken by {lease_holder(kube) or 'another run'}"
        raise LockBusyError(msg) from exc


def release_lease(kube: Kube, who: str) -> None:
    """Delete the lease if `who` still holds it."""
    found = kube.get_optional("lease", LEASE)
    if found is not None and section(found, "spec").get("holderIdentity") == who:
        kube.delete("lease", LEASE)


@contextmanager
def _file_lock(path: str | None, who: str) -> Generator[None]:
    if not path:
        yield
        return
    lock = Path(path)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as exc:
        current = lock.read_text(encoding="utf-8").strip() or "unknown"
        msg = f"{lock} is held by: {current}; wait or ask its owner"
        raise LockBusyError(msg) from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(f"{who} {datetime.now(tz=UTC).isoformat(timespec='seconds')}\n")
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


@contextmanager
def held(env: Environment, what: str) -> Generator[None]:
    """Hold the environment's lock file and, with cluster access, its lease while the block runs."""
    who = holder(what)
    settings = env.profile.settings
    with _file_lock(settings.get("lock_file"), who):
        if env.capabilities.skip_reason(CLUSTER):
            yield
            return
        take_lease(env.kube, who, int(settings.get("lock_lease_seconds", LEASE_SECONDS)))
        try:
            yield
        finally:
            release_lease(env.kube, who)
