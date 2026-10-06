"""The one place that starts external processes (kubectl, az, git)."""

from __future__ import annotations

import shlex
import subprocess  # nosec B404

from collections.abc import Callable
from collections.abc import Sequence

Runner = Callable[[Sequence[str], int], subprocess.CompletedProcess[str]]


class ProcessError(Exception):
    """An external command failed. The message holds the command line, so it can be pasted and rerun."""

    def __init__(self, command: Sequence[str], detail: str) -> None:
        self.command = shlex.join(command)
        # kubectl repeats client-side noise (E1005 memcache...) before the real error; keep the last line.
        lines = [line for line in detail.strip().splitlines() if line.strip()]
        super().__init__(f"{self.command}: {lines[-1] if lines else 'failed'}")


def run_process(args: Sequence[str], timeout: int) -> subprocess.CompletedProcess[str]:
    """Run a fixed argv, never through a shell; the caller checks the return code."""
    return subprocess.run(list(args), capture_output=True, text=True, timeout=timeout, check=False)  # nosec B603  # noqa: S603


def run_checked[E: ProcessError](
    runner: Runner, command: Sequence[str], timeout: int, error: type[E] = ProcessError
) -> str:
    """stdout of a command; `error` when it is missing, times out or exits non-zero."""
    try:
        result = runner(command, timeout)
    except FileNotFoundError as exc:
        raise error(command, f"{command[0]} not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise error(command, f"timed out after {timeout}s") from exc
    if result.returncode != 0:
        raise error(command, result.stderr or f"exit code {result.returncode}")
    return result.stdout
