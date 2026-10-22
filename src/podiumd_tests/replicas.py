"""Several pods per workload on an environment that runs one each (profile setting replicas_command)."""

from __future__ import annotations

import os
import shlex

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from podiumd_tests.lock import running_hold
from podiumd_tests.process import run_checked

if TYPE_CHECKING:
    from collections.abc import Generator

    from podiumd_tests.config import Profile
    from podiumd_tests.environment import Environment

SETTING = "replicas_command"
# podiumd-minikube's lock: a command started with this set to the lock file's line does not take the lock again.
HOLD_ENV = "MINIKUBE_LOCK_HOLD"
# `replicas on` waits for the StatefulSets and the redis master label; `off` up to 300 s for the label.
TIMEOUT = 600


def switches_replicas(profile: Profile) -> bool:
    """Whether tests that need several pods switch them on themselves (and so disrupt the environment)."""
    return bool(profile.settings.get(SETTING))


@contextmanager
def several_replicas(env: Environment) -> Generator[None]:
    """Runs `<replicas_command> on` before the block and `off` after it; a no-op without replicas_command.

    A podiumd-tests run holding settings.lock_file passes its hold on, so the command does not wait for it.
    """
    command = shlex.split(env.profile.settings.get(SETTING, ""))
    if not command:
        yield
        return
    lock = env.profile.settings.get("lock_file")
    hold = running_hold(Path(lock)) if lock else None
    previous = os.environ.get(HOLD_ENV)
    if hold:
        os.environ[HOLD_ENV] = hold
    try:
        run_checked(env.kube.runner, [*command, "on"], TIMEOUT)
        try:
            yield
        finally:
            run_checked(env.kube.runner, [*command, "off"], TIMEOUT)
    finally:
        if previous is None:
            os.environ.pop(HOLD_ENV, None)
        else:
            os.environ[HOLD_ENV] = previous
