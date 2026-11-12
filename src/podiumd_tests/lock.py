"""The environment lock: one writing run at a time, from a console, a pipeline or another agent.

Two locks, both taken when configured or reachable:
- a Lease podiumd-tests-lock in the environment's namespace, so runs on different machines and pipelines see each
  other; it names its holder and expires leaseDurationSeconds after acquireTime (podiumd-infra reads it the same way).
  A run renews it every third of settings.lock_lease_seconds (default 10 min) by raising leaseDurationSeconds, so a
  killed pipeline frees it within that window;
- the lock file of settings.lock_file, shared with other agents on the same machine: one line
  "<who> <what> <ISO start time>", taken exclusively (O_EXCL) and flock-ed by its holder while it runs.

A lock of this user@host whose holder no longer runs is stale: a killed run left it, and the next run takes it over.
The holder runs when its pid exists, its lock file is flock-ed (a holder in another PID namespace), or its lease was
renewed within the window. Taking over is atomic: the lock file under a guard flock, the Lease by resourceVersion.
SIGTERM (`timeout`) releases both locks, then stops the run as Ctrl-C does. `podiumd-tests lock` shows or breaks a
podiumd-tests hold.
"""

from __future__ import annotations

import fcntl
import getpass
import json
import os
import re
import signal
import socket
import sys
import threading

from contextlib import ExitStack
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
    from typing import TextIO

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.kube import Kube

HOLDER = "podiumd-tests"
LEASE = "podiumd-tests-lock"
LEASE_SECONDS = 600
# Renewals per lease window: a missed renewal or two does not let the lease expire.
RENEWALS = 3
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


@contextmanager
def file_lock(path: Path) -> Generator[None]:
    """Hold an exclusive lock on the file (created if absent) while the block runs; other processes wait."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class LockBusyError(Exception):
    """Another run holds the lock; the message names it."""


def _me() -> str:
    return f"{getpass.getuser()}@{socket.gethostname()}"


def holder(what: str) -> str:
    """Who takes the lock and for what, e.g. "podiumd-tests kees@laptop pid 4242 run full kees00"."""
    return f"{HOLDER} {_me()} pid {os.getpid()} {what}"


def is_stale(text: str, lock: Path | None = None) -> bool:
    """Whether the lock's holder is a run of this user@host that no longer runs.

    It runs while its pid exists or, for a lock file, while the file is flock-ed: a holder in another PID namespace.
    """
    found = re.search(rf"{HOLDER} (\S+) pid (\d+) ", text)
    if found is None or found[1] != _me():
        return False
    try:
        os.kill(int(found[2]), 0)
    except ProcessLookupError:
        return lock is None or not _is_flocked(lock)
    except PermissionError:
        return False
    return False


def _is_flocked(lock: Path) -> bool:
    """Whether a process holds a flock on the lock file."""
    try:
        handle = lock.open(encoding="utf-8")
    except FileNotFoundError:
        return False
    with handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def _lease(kube: Kube, who: str, seconds: int, now: datetime) -> dict[str, object]:
    return {
        "apiVersion": "coordination.k8s.io/v1",
        "kind": "Lease",
        "metadata": {"name": LEASE, "labels": {"app.kubernetes.io/managed-by": HOLDER}, "namespace": kube.namespace},
        "spec": {
            "holderIdentity": who,
            "acquireTime": now.strftime(TIME_FORMAT),
            "leaseDurationSeconds": seconds,
        },
    }


def lease_holder(kube: Kube, now: datetime | None = None) -> str | None:
    """Return the holder and start of the unexpired lease, or None when no run holds it."""
    return _unexpired_holder(kube.get_optional("lease", LEASE), now or datetime.now(tz=UTC))


def _unexpired_holder(found: JsonObject | None, now: datetime) -> str | None:
    """Return the holder and start of the lease, or None when there is none or it expired."""
    if found is None:
        return None
    spec: JsonObject = section(found, "spec")
    started = datetime.fromisoformat(str(spec.get("acquireTime")))
    expires = started + timedelta(seconds=int(str(spec.get("leaseDurationSeconds") or 0)))
    if expires < now:
        return None
    return f"{spec.get('holderIdentity')} since {started:%Y-%m-%d %H:%M}Z"


def _is_recently_renewed(found: JsonObject, seconds: int, now: datetime) -> bool:
    """Whether the lease's renewTime falls within two renewal intervals: its holder still runs."""
    renewed = section(found, "spec").get("renewTime")
    if not renewed:
        return False
    return now - datetime.fromisoformat(str(renewed)) < timedelta(seconds=2 * seconds / RENEWALS)


def take_lease(kube: Kube, who: str, seconds: int) -> None:
    """Take the lease for `seconds`; LockBusyError while another run holds it unexpired.

    An expired or stale lease is replaced at its resourceVersion, so of two runs taking it over one wins.
    """
    now = datetime.now(tz=UTC)
    found = kube.get_optional("lease", LEASE)
    current = _unexpired_holder(found, now)
    if found is not None and current and (not is_stale(current) or _is_recently_renewed(found, seconds, now)):
        msg = f"lease {LEASE} in {kube.namespace} is held by {current}; wait or ask its holder"
        raise LockBusyError(msg)
    lease = _lease(kube, who, seconds, now)
    verb = "create"
    if found is not None:
        verb = "replace"
        lease["metadata"] = {
            **section(lease, "metadata"),
            "resourceVersion": section(found, "metadata").get("resourceVersion"),
        }
    try:
        kube.run(verb, "-f", "-", stdin=json.dumps(lease))
    except KubeError as exc:  # another run took it in between
        msg = f"lease {LEASE} in {kube.namespace} was just taken by {lease_holder(kube) or 'another run'}"
        raise LockBusyError(msg) from exc


def has_renewed_lease(kube: Kube, who: str, seconds: int, now: datetime | None = None) -> bool:
    """Extend `who`'s lease to `seconds` from now; False when `who` no longer holds it.

    Raises leaseDurationSeconds and keeps acquireTime, so every reader still computes the expiry from acquireTime.
    """
    now = now or datetime.now(tz=UTC)
    found = kube.get_optional("lease", LEASE)
    if found is None or section(found, "spec").get("holderIdentity") != who:
        return False
    started = datetime.fromisoformat(str(section(found, "spec").get("acquireTime")))
    patch = [
        {"op": "test", "path": "/spec/holderIdentity", "value": who},
        {
            "op": "replace",
            "path": "/spec/leaseDurationSeconds",
            "value": int((now - started).total_seconds()) + seconds,
        },
        {"op": "add", "path": "/spec/renewTime", "value": now.strftime(TIME_FORMAT)},
    ]
    try:
        kube.run("patch", "lease", LEASE, "--type=json", "-p", json.dumps(patch))
    except KubeError:
        return False
    return True


def release_lease(kube: Kube, who: str) -> None:
    """Delete the lease if `who` still holds it."""
    found = kube.get_optional("lease", LEASE)
    if found is not None and section(found, "spec").get("holderIdentity") == who:
        kube.delete("lease", LEASE)


def running_hold(lock: Path) -> str | None:
    """Return the lock file's line while a running podiumd-tests process of this user@host holds it, else None."""
    try:
        line = lock.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return line if line.startswith(f"{HOLDER} {_me()} pid ") and not is_stale(line) else None


def _take_file(lock: Path, who: str) -> TextIO:
    """Create the lock file, taking over a stale one, and flock it; LockBusyError while another holds it.

    Under a guard flock, so of two runs taking over a stale file one wins. The returned handle keeps the flock.
    """
    with file_lock(lock.with_name(f"{lock.name}.guard")):
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError as exc:
            current = lock.read_text(encoding="utf-8").strip() or "unknown"
            if not is_stale(current, lock):
                msg = f"{lock} is held by: {current}; wait or ask its owner"
                raise LockBusyError(msg) from exc
            lock.unlink()
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        handle = os.fdopen(descriptor, "w", encoding="utf-8")
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.write(f"{who} {datetime.now(tz=UTC).isoformat(timespec='seconds')}\n")
        handle.flush()
    return handle


def _release(kube: Kube | None, lock: Path | None, who: str) -> None:
    """Release the lease and the lock file, each only while `who` still holds it."""
    if kube is not None:
        release_lease(kube, who)
    if lock is not None and lock.exists() and lock.read_text(encoding="utf-8").startswith(f"{who} "):
        lock.unlink(missing_ok=True)


def break_holds(env: Environment) -> list[str]:
    """Remove the environment's podiumd-tests holds (lease and lock file), never another owner's; what was removed."""
    removed: list[str] = []
    if not env.capabilities.skip_reason(CLUSTER):
        found = env.kube.get_optional("lease", LEASE)
        who = str(section(found, "spec").get("holderIdentity")) if found else ""
        if who.startswith(f"{HOLDER} "):
            env.kube.delete("lease", LEASE)
            removed.append(f"lease {LEASE}: {who}")
    setting = env.profile.settings.get("lock_file")
    lock = Path(setting) if setting else None
    if lock is not None and lock.exists():
        line = lock.read_text(encoding="utf-8").strip()
        if line.startswith(f"{HOLDER} "):
            lock.unlink(missing_ok=True)
            removed.append(f"{lock}: {line}")
    return removed


def holds(env: Environment) -> list[str]:
    """Describe who holds the environment's lease and lock file now."""
    found: list[str] = []
    if not env.capabilities.skip_reason(CLUSTER):
        found.append(f"lease {LEASE}: {lease_holder(env.kube) or 'free'}")
    setting = env.profile.settings.get("lock_file")
    if setting:
        lock = Path(setting)
        found.append(f"{lock}: {lock.read_text(encoding='utf-8').strip() if lock.exists() else 'free'}")
    return found


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
    with ExitStack() as stack:
        if lock is not None:
            stack.enter_context(_take_file(lock, who))
        stack.callback(_release, kube, lock, who)
        stack.enter_context(_leased(kube, who, settings))
        stack.enter_context(_interrupt_on_sigterm(lambda: _release(kube, lock, who)))
        taken = [str(lock)] if lock else []
        taken += [f"lease {LEASE} in {kube.namespace}"] if kube else []
        if taken:
            print(f"lock taken: {who} ({', '.join(taken)})", file=sys.stderr)
        yield


@contextmanager
def _leased(kube: Kube | None, who: str, settings: dict[str, str]) -> Generator[None]:
    """Hold the lease while the block runs, with cluster access, renewing it; _release returns it."""
    if kube is None:
        yield
        return
    seconds = int(settings.get("lock_lease_seconds", LEASE_SECONDS))
    take_lease(kube, who, seconds)
    stop = threading.Event()

    def renew() -> None:
        while not stop.wait(seconds / RENEWALS):
            if not has_renewed_lease(kube, who, seconds):
                print(f"lock lost: lease {LEASE} in {kube.namespace} is no longer {who}'s", file=sys.stderr)
                return

    renewer = threading.Thread(target=renew, name="lease-renewal", daemon=True)
    renewer.start()
    with ExitStack() as stack:
        stack.callback(renewer.join)
        stack.callback(stop.set)
        yield
