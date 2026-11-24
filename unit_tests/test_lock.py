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


def ledger_env(tmp_path, profile_factory, fake_runner):
    script = tmp_path / "env-ledger.py"
    script.write_text("", encoding="utf-8")
    # An absolute setting: REPO_ROOT.parent / script is script.
    profile = profile_factory(settings={"lock_file": str(tmp_path / "lock"), "env_ledger": str(script)})
    return Environment(profile, fake_runner, environ={})


def test_held_books_the_environment_in_the_env_ledger_and_closes_the_booking(tmp_path, profile_factory, fake_runner):
    booked = json.dumps({"ok": True, "booking": "test-env-1119-0900-ab12"})
    fake_runner.answers = {" book ": (0, booked), "env-ledger.py": (0, "")}
    with held(ledger_env(tmp_path, profile_factory, fake_runner), "run full"):
        assert (tmp_path / "lock").exists()
    ledger_calls = [call for call in fake_runner.calls if call[0].endswith("env-ledger.py")]
    assert [call[1:3] for call in ledger_calls] == [["book", "test-env"], ["done", "test-env"]]
    assert ledger_calls[0][ledger_calls[0].index("--ignore-lock-holder") + 1] == holder("run full")
    assert ledger_calls[1][3] == "test-env-1119-0900-ab12"


def test_a_conflicting_booking_refuses_and_releases_the_lock(tmp_path, profile_factory, fake_runner):
    refused = {"ok": False, "conflicts": [{"agent": "podiumd-minikube", "what": "reset"}], "locks": []}
    # The ledger exits 3 with this on stdout; the code reads only "ok".
    fake_runner.answers = {" book ": (0, json.dumps(refused))}
    env = ledger_env(tmp_path, profile_factory, fake_runner)
    with pytest.raises(LockBusyError, match="podiumd-minikube: reset"), held(env, "bootstrap"):  # noqa: WPS328  # enter is under test
        ...
    assert not (tmp_path / "lock").exists()


def test_a_run_beats_podiumd_tests_own_booking_and_leaves_it_open(tmp_path, profile_factory, fake_runner):
    own = {"agent": "podiumd-tests", "id": "test-env-1124-1116-a40f", "state": "booked", "to": "2026-11-24T11:46:03Z"}
    fake_runner.answers = {
        " book ": (0, json.dumps({"ok": False, "conflicts": [own], "locks": []})),
        "env-ledger.py": (0, ""),
    }
    with held(ledger_env(tmp_path, profile_factory, fake_runner), "run chaos"):
        assert (tmp_path / "lock").exists()
    ledger_calls = [call[1:4] for call in fake_runner.calls if call[0].endswith("env-ledger.py")]
    assert ledger_calls[1:] == [["start", "test-env", "test-env-1124-1116-a40f"]]


def test_another_agents_booking_next_to_our_own_still_refuses(tmp_path, profile_factory, fake_runner):
    conflicts = [
        {"agent": "podiumd-tests", "id": "a", "what": "drain"},
        {"agent": "podiumd-minikube", "what": "deploy"},
    ]
    fake_runner.answers = {" book ": (0, json.dumps({"ok": False, "conflicts": conflicts, "locks": []}))}
    env = ledger_env(tmp_path, profile_factory, fake_runner)
    with pytest.raises(LockBusyError, match="podiumd-minikube: deploy"), held(env, "run chaos"):  # noqa: WPS328  # enter is under test
        ...


def test_no_booking_where_the_env_ledger_is_absent(tmp_path, profile_factory, fake_runner, capsys):
    env = Environment(profile_factory(settings={"env_ledger": str(tmp_path / "absent.py")}), fake_runner, environ={})
    with held(env, "run full"):
        assert "not booked: env ledger" in capsys.readouterr().err
    assert not any("absent.py" in call[0] for call in fake_runner.calls)


def outer_env(profile_factory, fake_runner, lease_json):
    fake_runner.answers = {"get deployments": (0, json.dumps({"items": []})), "get lease": (0, lease_json)}
    return Environment(profile_factory(settings={"lock_file": "/nonexistent/lock"}), fake_runner, environ={})


def test_an_orchestrators_hold_is_checked_and_nothing_is_taken(profile_factory, fake_runner, monkeypatch):
    monkeypatch.setenv("PODIUMD_TESTS_HELD_BY", "podiumd-infra run 7 Release Gate x")
    env = outer_env(profile_factory, fake_runner, lease("podiumd-infra run 7 Release Gate x", datetime.now(tz=UTC)))
    with held(env, "run full"):
        ...
    assert not any(verb in call for call in fake_runner.calls for verb in ("create", "replace", "patch", "delete"))


@pytest.mark.parametrize(
    ("lease_json", "named"),
    [("", "held by nobody"), (lease("podiumd-infra run 8 Release Gate x", datetime.now(tz=UTC)), "run 8")],
    ids=["absent", "another"],
)
def test_an_orchestrators_hold_refuses_when_the_lease_names_another(
    profile_factory, fake_runner, monkeypatch, lease_json, named
):
    monkeypatch.setenv("PODIUMD_TESTS_HELD_BY", "podiumd-infra run 7 Release Gate x")
    env = outer_env(profile_factory, fake_runner, lease_json)
    with pytest.raises(LockBusyError, match=named), held(env, "run full"):  # noqa: WPS328  # enter is under test
        ...


def test_an_orchestrators_hold_needs_the_cluster(profile_factory, fake_runner, monkeypatch):
    monkeypatch.setenv("PODIUMD_TESTS_HELD_BY", "podiumd-infra run 7")
    env = Environment(profile_factory(), fake_runner, environ={})
    with pytest.raises(LockBusyError, match="cannot be read"), held(env, "run full"):  # noqa: WPS328  # enter is under test
        ...
