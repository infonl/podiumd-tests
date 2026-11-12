"""Unit tests for the environment lock's lease and lock file."""

import fcntl
import getpass
import json
import os
import signal
import socket

from datetime import UTC
from datetime import datetime
from datetime import timedelta

import pytest

from podiumd_tests.environment import Environment
from podiumd_tests.kube import Kube
from podiumd_tests.lock import LockBusyError
from podiumd_tests.lock import break_holds
from podiumd_tests.lock import has_renewed_lease
from podiumd_tests.lock import held
from podiumd_tests.lock import holder
from podiumd_tests.lock import holds
from podiumd_tests.lock import is_stale
from podiumd_tests.lock import lease_holder
from podiumd_tests.lock import release_lease
from podiumd_tests.lock import running_hold
from podiumd_tests.lock import take_lease


def lease(who, started, seconds=3600, **fields):
    spec = {
        "holderIdentity": who,
        "acquireTime": started.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "leaseDurationSeconds": seconds,
        **fields,
    }
    return json.dumps({"metadata": {"resourceVersion": "7"}, "spec": spec})


def test_a_held_lease_refuses_with_its_holder(fake_runner):
    fake_runner.answers = {"get lease": (0, lease("podiumd-tests ci@runner run full", datetime.now(tz=UTC)))}
    with pytest.raises(LockBusyError, match="ci@runner run full"):
        take_lease(Kube("ctx", "podiumd", fake_runner), "me", 3600)


def test_an_expired_lease_is_taken_over(fake_runner):
    old = datetime.now(tz=UTC) - timedelta(hours=4)
    fake_runner.answers = {"get lease": (0, lease("old run", old)), "": (0, "")}
    take_lease(Kube("ctx", "podiumd", fake_runner), "me", 3600)
    replaced = json.loads(fake_runner.stdins[[c[5:7] for c in fake_runner.calls].index(["replace", "-f"])])
    assert (replaced["spec"]["holderIdentity"], replaced["metadata"]["resourceVersion"]) == ("me", "7")


def test_no_lease_means_no_holder(fake_runner):
    fake_runner.answers = {"get lease": (0, "")}
    assert lease_holder(Kube("ctx", "podiumd", fake_runner)) is None


def test_release_deletes_only_its_own_lease(fake_runner):
    fake_runner.answers = {"get lease": (0, lease("other", datetime.now(tz=UTC))), "": (0, "")}
    release_lease(Kube("ctx", "podiumd", fake_runner), "me")
    assert not any("delete" in c for c in fake_runner.calls)


def test_release_deletes_its_own_lease(fake_runner):
    fake_runner.answers = {"get lease": (0, lease("me", datetime.now(tz=UTC))), "": (0, "")}
    release_lease(Kube("ctx", "podiumd", fake_runner), "me")
    assert any("delete" in c for c in fake_runner.calls)


def test_a_lease_another_run_creates_first_refuses(fake_runner):
    fake_runner.answers = {"get lease": (0, ""), "delete lease": (0, ""), "create": (1, "AlreadyExists")}
    with pytest.raises(LockBusyError, match="was just taken by another run"):
        take_lease(Kube("ctx", "podiumd", fake_runner), "me", 3600)


def test_lock_file_is_taken_and_released_without_cluster(tmp_path, profile_factory, fake_runner):
    lock = tmp_path / "lock"
    env = Environment(profile_factory(settings={"lock_file": str(lock)}), fake_runner, environ={})
    with held(env, "bootstrap env"):
        assert " bootstrap env " in lock.read_text(encoding="utf-8")
    assert not lock.exists()


def test_a_held_lock_file_refuses_and_names_its_holder(tmp_path, profile_factory, fake_runner):
    lock = tmp_path / "lock"
    lock.write_text("podiumd-minikube deploy 2026-10-07T10:00:00\n", encoding="utf-8")
    env = Environment(profile_factory(settings={"lock_file": str(lock)}), fake_runner, environ={})
    with pytest.raises(LockBusyError, match="held by: podiumd-minikube deploy"), held(env, "bootstrap"):  # noqa: WPS328  # enter is under test
        ...
    assert lock.exists()


# Above any pid: Linux's pid_max is at most 2**22 (PID_MAX_LIMIT), macOS's highest pid is 99998.
DEAD_PID = 2**22 + 1


def dead_pid():
    """A pid no process can have, on Linux and macOS alike."""
    return DEAD_PID


def test_a_lock_of_a_dead_run_of_this_host_is_stale():
    me = f"{getpass.getuser()}@{socket.gethostname()}"
    assert is_stale(f"podiumd-tests {me} pid {dead_pid()} run full minikube 2026-10-10T17:18:01+00:00")
    assert not is_stale(f"podiumd-tests {me} pid {os.getpid()} run full minikube 2026-10-10T17:18:01+00:00")
    assert not is_stale(f"podiumd-tests other@elsewhere pid {dead_pid()} run full minikube")
    assert not is_stale("podiumd-minikube deploy 2026-10-07T10:00:00")


def test_a_stale_lock_file_is_taken_over(tmp_path, profile_factory, fake_runner):
    lock = tmp_path / "lock"
    lock.write_text(f"{holder('run full').replace(str(os.getpid()), str(dead_pid()))} 2026-10-10\n", encoding="utf-8")
    env = Environment(profile_factory(settings={"lock_file": str(lock)}), fake_runner, environ={})
    with held(env, "bootstrap env"):
        assert f" pid {os.getpid()} bootstrap env " in lock.read_text(encoding="utf-8")
    assert not lock.exists()


def test_sigterm_releases_the_lock_file(tmp_path, profile_factory, fake_runner):
    lock = tmp_path / "lock"
    env = Environment(profile_factory(settings={"lock_file": str(lock)}), fake_runner, environ={})
    with pytest.raises(KeyboardInterrupt), held(env, "run full"):
        os.kill(os.getpid(), signal.SIGTERM)
    assert not lock.exists()


def test_a_stale_lease_is_taken_over(fake_runner):
    stale = holder("run full").replace(str(os.getpid()), str(dead_pid()))
    fake_runner.answers = {"get lease": (0, lease(stale, datetime.now(tz=UTC))), "": (0, "")}
    take_lease(Kube("ctx", "podiumd", fake_runner), "me", 3600)
    assert any(c[5:7] == ["replace", "-f"] for c in fake_runner.calls)


def test_release_leaves_a_lock_file_another_took_over(tmp_path, profile_factory, fake_runner):
    lock = tmp_path / "lock"
    env = Environment(profile_factory(settings={"lock_file": str(lock)}), fake_runner, environ={})
    with held(env, "run full"):
        lock.write_text("podiumd-minikube deploy 2026-10-10T18:00:00\n", encoding="utf-8")
    assert lock.read_text(encoding="utf-8").startswith("podiumd-minikube")


def test_running_hold_is_the_line_of_a_running_podiumd_tests_process(tmp_path):
    lock = tmp_path / "lock"
    assert running_hold(lock) is None
    lock.write_text(f"{holder('run chaos minikube')} 2026-10-22T10:00:00+00:00\n", encoding="utf-8")
    assert running_hold(lock) == f"{holder('run chaos minikube')} 2026-10-22T10:00:00+00:00"
    lock.write_text("podiumd-minikube deploy 2026-10-22T10:00:00+00:00\n", encoding="utf-8")
    assert running_hold(lock) is None


def test_renewal_raises_the_duration_and_keeps_the_acquire_time(fake_runner):
    started = datetime.now(tz=UTC) - timedelta(minutes=20)
    fake_runner.answers = {"get lease": (0, lease("me", started, 600)), "patch": (0, "")}
    assert has_renewed_lease(Kube("ctx", "podiumd", fake_runner), "me", 600, now=started + timedelta(minutes=20))
    patch = json.loads(fake_runner.calls[-1][-1])
    assert patch[0] == {"op": "test", "path": "/spec/holderIdentity", "value": "me"}
    assert patch[1] == {"op": "replace", "path": "/spec/leaseDurationSeconds", "value": 1800}


def test_renewal_of_a_lease_another_holds_fails(fake_runner):
    fake_runner.answers = {"get lease": (0, lease("other", datetime.now(tz=UTC)))}
    assert not has_renewed_lease(Kube("ctx", "podiumd", fake_runner), "me", 600)
    assert not any("patch" in c for c in fake_runner.calls)


def test_a_recently_renewed_lease_of_a_dead_pid_is_not_taken_over(fake_runner):
    stale = holder("run full").replace(str(os.getpid()), str(dead_pid()))
    renewed = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    fake_runner.answers = {"get lease": (0, lease(stale, datetime.now(tz=UTC), renewTime=renewed))}
    with pytest.raises(LockBusyError):
        take_lease(Kube("ctx", "podiumd", fake_runner), "me", 600)


def test_a_flocked_lock_file_of_an_invisible_pid_is_held(tmp_path, profile_factory, fake_runner):
    lock = tmp_path / "lock"
    other = holder("run full").replace(str(os.getpid()), str(dead_pid()))
    lock.write_text(f"{other} 2026-11-12T15:00:00+00:00\n", encoding="utf-8")
    env = Environment(profile_factory(settings={"lock_file": str(lock)}), fake_runner, environ={})
    with lock.open(encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        with pytest.raises(LockBusyError, match="is held by"):
            held(env, "bootstrap").__enter__()
    with held(env, "bootstrap"):
        assert lock.read_text(encoding="utf-8").startswith(holder("bootstrap"))


def test_held_logs_the_lock_and_breaking_removes_only_podiumd_tests_holds(
    tmp_path, profile_factory, fake_runner, capsys
):
    lock = tmp_path / "lock"
    env = Environment(profile_factory(settings={"lock_file": str(lock)}), fake_runner, environ={})
    with held(env, "run full"):
        assert f"lock taken: {holder('run full')}" in capsys.readouterr().err
        assert holds(env) == [f"{lock}: {lock.read_text(encoding='utf-8').strip()}"]
    lock.write_text("podiumd-minikube deploy 2026-11-12T15:00:00+00:00\n", encoding="utf-8")
    assert break_holds(env) == []
    lock.write_text(f"{holder('run full')} 2026-11-12T15:00:00+00:00\n", encoding="utf-8")
    assert break_holds(env) == [f"{lock}: {holder('run full')} 2026-11-12T15:00:00+00:00"]
    assert not lock.exists()
