"""Unit tests for switching several pods on around a block."""

import os
import subprocess

from podiumd_tests.lock import holder
from podiumd_tests.replicas import HOLD_ENV
from podiumd_tests.replicas import several_replicas
from podiumd_tests.replicas import switches_replicas


class HoldRecorder:
    """Records each command with the lock hold it saw in the process environment."""

    def __init__(self):
        self.calls = []

    def __call__(self, args, _timeout, _stdin=None):
        self.calls.append((list(args), os.environ.get(HOLD_ENV)))
        return subprocess.CompletedProcess(list(args), 0, "", "")


def test_replicas_are_switched_on_for_the_block_and_off_after_it(tmp_path, env_factory, profile_factory):
    lock = tmp_path / "lock"
    line = f"{holder('run chaos minikube')} 2026-10-22T10:00:00+00:00"
    lock.write_text(line + "\n", encoding="utf-8")
    settings = {"replicas_command": "/opt/podiumd-minikube/bin/replicas", "lock_file": str(lock)}
    recorder = HoldRecorder()
    env = env_factory(profile_factory(settings=settings), runner=recorder)
    assert switches_replicas(env.profile)
    with several_replicas(env):
        assert recorder.calls == [(["/opt/podiumd-minikube/bin/replicas", "on"], line)]
    assert recorder.calls[1] == (["/opt/podiumd-minikube/bin/replicas", "off"], line)
    assert HOLD_ENV not in os.environ


def test_without_replicas_command_nothing_runs(env_factory, fake_runner):
    env = env_factory()
    assert not switches_replicas(env.profile)
    with several_replicas(env):
        pass
    assert fake_runner.calls == []
