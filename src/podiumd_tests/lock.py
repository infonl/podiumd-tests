"""The environment lock: one writing run at a time, from a console, a pipeline or another agent.

Two locks, both taken when configured or reachable:
- a Lease podiumd-tests-lock in the environment's namespace, so runs on different machines and pipelines see each
  other; it names its holder and expires leaseDurationSeconds after acquireTime (podiumd-infra reads it the same way).
  A run renews it every third of settings.lock_lease_seconds (default 10 min) by raising leaseDurationSeconds, so a
  killed pipeline frees it within that window;
- the lock file of settings.lock_file (relative to the directory that holds podiumd-tests), shared with other agents
  on the same machine: one line "<who> <what> <ISO start time>", taken exclusively (O_EXCL) and flock-ed by its
  holder while it runs.

A lock of this user@host whose holder no longer runs is stale: a killed run left it, and the next run takes it over.
The holder runs when its pid exists, its lock file is flock-ed (a holder in another PID namespace), or its lease was
renewed within the window. Taking over is atomic: the lock file under a guard flock, the Lease by resourceVersion.
SIGTERM (`timeout`) releases both locks, then stops the run as Ctrl-C does. `podiumd-tests lock` shows or breaks a
podiumd-tests hold.

With settings.env_ledger (env-ledger.py, relative to the directory that holds podiumd-tests), the hold is also a
disruptive booking of the environment named as the profile in that ledger, kept alive by heartbeats and closed when
the hold ends. The ledger skips the run's own locks (--ignore-lock-holder).
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
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING

from podiumd_tests.capabilities import CLUSTER
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kube import KubeError
from podiumd_tests.process import ProcessError
from podiumd_tests.process import run_checked

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Generator
    from pathlib import Path
    from typing import TextIO

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.kube import Kube
    from podiumd_tests.process import Runner

HOLDER = "podiumd-tests"
LEASE = "podiumd-tests-lock"
LEASE_SECONDS = 600
# Renewals per lease window: a missed renewal or two does not let the lease expire.
RENEWALS = 3
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
LEDGER_TIMEOUT = 90
BOOKING = timedelta(hours=1)
# The ledger expires an active booking after 20 min without a heartbeat.
HEARTBEAT_SECONDS = 300


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


def _release(kube: Kube | None, lock: Path | None, who: str, booking: Booking | None = None) -> None:
    """Close the booking and release the lease and the lock file, each only while `who` still holds it."""
    if booking is not None:
        booking.close()
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
    lock = env.profile.setting_path("lock_file")
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
    lock = env.profile.setting_path("lock_file")
    if lock is not None:
        lock_holder = lock.read_text(encoding="utf-8").strip() if lock.exists() else "free"
        found.append(f"{lock}: {lock_holder}")
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
    """Hold the environment's lock file, with cluster access its lease, and its env ledger booking during the block."""
    who = holder(what)
    settings = env.profile.settings
    lock = env.profile.setting_path("lock_file")
    kube = None if env.capabilities.skip_reason(CLUSTER) else env.kube
    with ExitStack() as stack:
        if lock is not None:
            stack.enter_context(_take_file(lock, who))
        stack.callback(_release, kube, lock, who)
        stack.enter_context(_leased(kube, who, settings))
        booking = stack.enter_context(_booked(env, who, what))
        stack.enter_context(_interrupt_on_sigterm(lambda: _release(kube, lock, who, booking)))
        taken = [str(lock)] if lock else []
        taken += [f"lease {LEASE} in {kube.namespace}"] if kube else []
        taken += [f"env ledger booking {booking.booking}"] if booking else []
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

    def is_renewed() -> bool:
        if has_renewed_lease(kube, who, seconds):
            return True
        print(f"lock lost: lease {LEASE} in {kube.namespace} is no longer {who}'s", file=sys.stderr)
        return False

    with _every(seconds / RENEWALS, is_renewed):
        yield


@contextmanager
def _every(seconds: float, action: Callable[[], bool]) -> Generator[None]:
    """Call action every `seconds` in a thread while the block runs, until it returns False."""
    stop = threading.Event()

    def repeat() -> None:
        while not stop.wait(seconds):
            if not action():
                return

    thread = threading.Thread(target=repeat, name="lock-renewal", daemon=True)
    thread.start()
    with ExitStack() as stack:
        stack.callback(thread.join)
        stack.callback(stop.set)
        yield


@dataclass
class Booking:
    """The hold's open booking in the env ledger."""

    script: str
    ledger: str
    runner: Runner
    booking: str
    end: datetime
    is_open: bool = field(default=True)
    # A booking made by hand ahead of the run: the run beats it but leaves it open for the work after it.
    is_own: bool = field(default=True)

    def call(self, verb: str, *args: str) -> None:
        """Run an env-ledger.py verb on this booking as podiumd-tests."""
        command = [self.script, verb, self.ledger, self.booking, *args, "--agent", HOLDER]
        run_checked(self.runner, command, LEDGER_TIMEOUT)

    def has_beaten(self) -> bool:
        """Send a heartbeat, extending the booking when less than half of BOOKING remains; False once closed."""
        if not self.is_open:
            return False
        now = datetime.now(tz=UTC)
        extend = self.end - now < BOOKING / 2
        try:
            self.call("heartbeat", *(["--extend", _minutes(BOOKING)] if extend else []))
        except ProcessError as exc:
            print(f"env ledger heartbeat failed: {exc}", file=sys.stderr)
            return True
        if extend:
            self.end = now + BOOKING
        return True

    def close(self) -> None:
        """Mark the booking done, once."""
        if not self.is_open:
            return
        self.is_open = False
        if not self.is_own:
            return
        try:
            self.call("done")
        except ProcessError as exc:
            print(f"env ledger booking {self.booking} not closed: {exc}", file=sys.stderr)


@contextmanager
def _booked(env: Environment, who: str, what: str) -> Generator[Booking | None]:
    """Book the environment while the block runs, sending heartbeats; None without a ledger."""
    booking = book(env, who, what)
    if booking is None:
        yield None
        return
    with ExitStack() as stack:
        stack.callback(booking.close)
        stack.enter_context(_every(HEARTBEAT_SECONDS, booking.has_beaten))
        yield booking


def _minutes(span: timedelta) -> str:
    return f"{int(span.total_seconds() // 60)}m"


def book(env: Environment, who: str, what: str) -> Booking | None:
    """Book and start the environment in settings.env_ledger; None without a ledger on this host.

    LockBusyError when the ledger refuses or fails. `who` holds the run's own locks, which the ledger skips.
    """
    path = env.profile.setting_path("env_ledger")
    if path is None:
        return None
    script = str(path)
    if not path.exists():
        print(f"not booked: env ledger {script} not found on this host", file=sys.stderr)
        return None
    ledger = env.profile.name
    command = [
        *(script, "book", ledger, "--what", what, "--for", _minutes(BOOKING), "--disruptive", "--start", "--json"),
        *("--ignore-lock-holder", who, "--agent", HOLDER),
    ]
    result = env.kube.runner(command, LEDGER_TIMEOUT)
    try:
        answer: JsonObject = json.loads(result.stdout)
    except json.JSONDecodeError:
        answer = {"ok": False, "error": result.stderr.strip() or f"exit code {result.returncode}"}
    end = datetime.now(tz=UTC) + BOOKING
    booking = Booking(script, ledger, env.kube.runner, str(answer.get("booking")), end)
    return booking if answer.get("ok") else _join_own(booking, answer)


def _join_own(booking: Booking, answer: JsonObject) -> Booking:
    """Join podiumd-tests' own booking (one booked by hand for this work) when it is the only conflict.

    LockBusyError for any other refusal.
    """
    conflicts = entries(answer.get("conflicts"))
    own = [other for other in conflicts if other.get("agent") == HOLDER]
    if answer.get("locks") or len(own) != 1 or len(conflicts) != 1:
        msg = f"env ledger refused {booking.ledger}: {_refusal(answer)}"
        raise LockBusyError(msg)
    booking.is_own = False
    booking.booking = str(own[0]["id"])
    booking.end = datetime.fromisoformat(str(own[0]["to"]))
    if own[0].get("state") == "booked":
        booking.call("start")
    return booking


def _refusal(answer: JsonObject) -> str:
    """Return the ledger's error, conflicting bookings and lock holders in one line."""
    parts = [str(answer["error"])] if answer.get("error") else []
    conflicts = entries(answer.get("conflicts"))
    parts += [f"{other['agent']}: {other['what']}" for other in conflicts]
    locks = entries(answer.get("locks"))
    parts += [f"{lock['lock']}: {lock['holder']}" for lock in locks]
    return "; ".join(parts) or "refused"
