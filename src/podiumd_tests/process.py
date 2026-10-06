"""The one place that starts external processes (kubectl, az, git)."""

from __future__ import annotations

import shlex
import subprocess  # nosec B404

from typing import TYPE_CHECKING
from typing import Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence


class Runner(Protocol):  # pylint: disable=too-few-public-methods  # a callable protocol has one method
    """Starts a process; unit tests pass a fake one."""

    def __call__(
        self, args: Sequence[str], timeout: int, stdin: str | None = None, /
    ) -> subprocess.CompletedProcess[str]:
        """Run args; stdin, when given, is the process's standard input (keeps secrets out of argv)."""
        ...


class ProcessError(Exception):
    """An external command failed. The message holds the command line, so it can be pasted and rerun."""

    def __init__(self, command: Sequence[str], detail: str) -> None:
        self.command = shlex.join(command)
        # kubectl repeats client-side noise (E1005 memcache...) before the real error; keep the last line.
        lines = [line for line in detail.strip().splitlines() if line.strip()]
        super().__init__(f"{self.command}: {lines[-1] if lines else 'failed'}")


def run_process(args: Sequence[str], timeout: int, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run a fixed argv, never through a shell; the caller checks the return code."""
    return subprocess.run(  # nosec B603  # noqa: S603
        list(args), input=stdin, capture_output=True, text=True, timeout=timeout, check=False
    )


def run_checked[E: ProcessError](
    runner: Runner, command: Sequence[str], timeout: int, error: type[E] = ProcessError, stdin: str | None = None
) -> str:
    """stdout of a command; `error` when it is missing, times out or exits non-zero."""
    try:
        result = runner(command, timeout, stdin)
    except FileNotFoundError as exc:
        raise error(command, f"{command[0]} not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise error(command, f"timed out after {timeout}s") from exc
    if result.returncode != 0:
        raise error(command, result.stderr or f"exit code {result.returncode}")
    return result.stdout
