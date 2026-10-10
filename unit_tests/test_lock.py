"""Unit tests for the environment lock's lease and lock file."""

import getpass
import json
import os
import signal
import socket

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from pathlib import Path

import pytest

from podiumd_tests.environment import Environment
from podiumd_tests.kube import Kube
from podiumd_tests.lock import LockBusyError
from podiumd_tests.lock import held
from podiumd_tests.lock import holder
from podiumd_tests.lock import is_stale
from podiumd_tests.lock import lease_holder
from podiumd_tests.lock import release_lease
from podiumd_tests.lock import take_lease


def lease(who, started, seconds=3600):
    spec = {
        "holderIdentity": who,
        "acquireTime": started.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "leaseDurationSeconds": seconds,
    }
    return json.dumps({"spec": spec})


def test_a_held_lease_refuses_with_its_holder(fake_runner):
    fake_runner.answers = {"get lease": (0, lease("podiumd-tests ci@runner run full", datetime.now(tz=UTC)))}
    with pytest.raises(LockBusyError, match="ci@runner run full"):
        take_lease(Kube("ctx", "podiumd", fake_runner), "me", 3600)


def test_an_expired_lease_is_taken_over(fake_runner):
    old = datetime.now(tz=UTC) - timedelta(hours=4)
    fake_runner.answers = {"get lease": (0, lease("old run", old)), "": (0, "")}
    take_lease(Kube("ctx", "podiumd", fake_runner), "me", 3600)
    created = fake_runner.stdins[[c[5:7] for c in fake_runner.calls].index(["create", "-f"])]
    assert json.loads(created)["spec"]["holderIdentity"] == "me"


def test_no_lease_means_no_holder(fake_runner):
    fake_runner.answers = {"get lease": (0, "")}
    assert lease_holder(Kube("ctx", "podiumd", fake_runner)) is None


def test_release_deletes_only_its_own_lease(fake_runner):
    fake_runner.answers = {"get lease": (0, lease("other", datetime.now(tz=UTC))), "": (0, "")}
    release_lease(Kube("ctx", "podiumd", fake_runner), "me")
    assert not any("delete" in c for c in fake_runner.calls)


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
    with pytest.raises(LockBusyError, match="held by: podiumd-minikube deploy"), held(env, "bootstrap"):
        pass
    assert lock.exists()


def dead_pid():
    """A pid above the kernel's highest, so no process has it."""
    return int(Path("/proc/sys/kernel/pid_max").read_text(encoding="utf-8")) + 1


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
    assert any(c[5:7] == ["create", "-f"] for c in fake_runner.calls)


def test_release_leaves_a_lock_file_another_took_over(tmp_path, profile_factory, fake_runner):
    lock = tmp_path / "lock"
    env = Environment(profile_factory(settings={"lock_file": str(lock)}), fake_runner, environ={})
    with held(env, "run full"):
        lock.write_text("podiumd-minikube deploy 2026-10-10T18:00:00\n", encoding="utf-8")
    assert lock.read_text(encoding="utf-8").startswith("podiumd-minikube")
