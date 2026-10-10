"""The environment lock: one writing run at a time, from a console, a pipeline or another agent.

Two locks, both taken when configured or reachable:
- a Lease podiumd-tests-lock in the environment's namespace, so runs on different machines see
  each other; it names its holder and expires after settings.lock_lease_seconds (default 3 h),
  after which the next run takes it over;
- the lock file of settings.lock_file, shared with other agents on the same machine: one line
  "<who> <what> <ISO start time>", taken exclusively (O_EXCL).

A lock whose holder names this user@host and a pid that no longer runs is stale: a killed run
left it, and the next run takes it over. SIGTERM (`timeout`) releases both locks, then stops the
run as Ctrl-C does.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import signal
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
    from collections.abc import Callable
    from collections.abc import Generator

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.kube import Kube

HOLDER = "podiumd-tests"
LEASE = "podiumd-tests-lock"
LEASE_SECONDS = 3 * 3600


class LockBusyError(Exception):
    """Another run holds the lock; the message names it."""


def _me() -> str:
    return f"{getpass.getuser()}@{socket.gethostname()}"


def holder(what: str) -> str:
    """Who takes the lock and for what, e.g. "podiumd-tests kees@laptop pid 4242 run full kees00"."""
    return f"{HOLDER} {_me()} pid {os.getpid()} {what}"


def is_stale(text: str) -> bool:
    """Whether the lock's holder is a run of this user@host whose process no longer runs."""
    found = re.search(rf"{HOLDER} (\S+) pid (\d+) ", text)
    if found is None or found[1] != _me():
        return False
    try:
        os.kill(int(found[2]), 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


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
    if current and not is_stale(current):
        msg = f"lease {LEASE} in {kube.namespace} is held by {current}; wait or ask its holder"
        raise LockBusyError(msg)
    kube.delete("lease", LEASE)  # an expired or stale one
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


def _take_file(lock: Path, who: str) -> None:
    """Create the lock file, taking over a stale one; LockBusyError while another holds it."""
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as exc:
        current = lock.read_text(encoding="utf-8").strip() or "unknown"
        if not is_stale(current):
            msg = f"{lock} is held by: {current}; wait or ask its owner"
            raise LockBusyError(msg) from exc
        lock.unlink()
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(f"{who} {datetime.now(tz=UTC).isoformat(timespec='seconds')}\n")


def _release(kube: Kube | None, lock: Path | None, who: str) -> None:
    """Release the lease and the lock file, each only while `who` still holds it."""
    if kube is not None:
        release_lease(kube, who)
    if lock is not None and lock.exists() and lock.read_text(encoding="utf-8").startswith(f"{who} "):
        lock.unlink(missing_ok=True)


@contextmanager
def _interrupt_on_sigterm(release: Callable[[], None]) -> Generator[None]:
    """On SIGTERM release the locks, then stop the run as Ctrl-C does.

    Releasing first, because a run interrupted inside a Playwright call can hang in its teardown.
    """

    def stop(_signum: int, _frame: object) -> None:
        release()
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


@contextmanager
def held(env: Environment, what: str) -> Generator[None]:
    """Hold the environment's lock file and, with cluster access, its lease while the block runs."""
    who = holder(what)
    settings = env.profile.settings
    lock = Path(settings["lock_file"]) if settings.get("lock_file") else None
    kube = None if env.capabilities.skip_reason(CLUSTER) else env.kube
    if lock is not None:
        _take_file(lock, who)
    try:
        if kube is not None:
            take_lease(kube, who, int(settings.get("lock_lease_seconds", LEASE_SECONDS)))
        with _interrupt_on_sigterm(lambda: _release(kube, lock, who)):
            yield
    finally:
        _release(kube, lock, who)
