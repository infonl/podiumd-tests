"""The one place that starts external processes (kubectl, az, git)."""

from __future__ import annotations

import subprocess  # nosec B404

from collections.abc import Callable
from collections.abc import Sequence

Runner = Callable[[Sequence[str], int], subprocess.CompletedProcess[str]]


def run_process(args: Sequence[str], timeout: int) -> subprocess.CompletedProcess[str]:
    """Run a fixed argv, never through a shell; the caller checks the return code."""
    return subprocess.run(list(args), capture_output=True, text=True, timeout=timeout, check=False)  # nosec B603  # noqa: S603
