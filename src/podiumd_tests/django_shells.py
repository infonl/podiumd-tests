"""Long-lived Django shells: one per deployment, so a snippet does not pay Django's start (3 to 5 s) each time.

The shell sets Django up once and forks a child per request; the child runs the code from the clean state after
setup, so nothing one request caches reaches the next, and its database connections are its own. Code and results
travel over the shell's stdin and stdout as JSON lines, as the one-shot shell keeps them out of argv.
"""

from __future__ import annotations

import json
import queue
import subprocess  # nosec B404
import threading

from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.process import ProcessError
from podiumd_tests.process import start_process

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import IO

# Runs in the deployment's `manage.py shell -c`: one JSON line per request, one RESPONSE line per answer.
SERVER = r"""
import contextlib, io, json, os, sys, traceback
from django import db
answers = sys.stdout
for line in sys.stdin:
    request = json.loads(line)
    db.connections.close_all()
    read, write = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read)
        printed, error = io.StringIO(), None
        try:
            with contextlib.redirect_stdout(printed):
                exec(request["code"], {"__name__": "__main__"})
        except BaseException:
            error = traceback.format_exc()
        with os.fdopen(write, "w") as pipe:
            pipe.write(json.dumps({"out": printed.getvalue(), "error": error}))
        os._exit(0)
    os.close(write)
    with os.fdopen(read) as pipe:
        answer = pipe.read()
    os.waitpid(child, 0)
    answers.write(f"PTEST_RESPONSE {answer}\n")
    answers.flush()
"""
RESPONSE = "PTEST_RESPONSE "


class ShellGoneError(Exception):
    """The long-lived shell died or did not answer in time; the caller runs the code in a one-shot shell."""


class DjangoShell:
    """One long-lived `manage.py shell` of a deployment, started by its kubectl command."""

    def __init__(self, command: Sequence[str], error: type[ProcessError] = ProcessError) -> None:
        self.command: list[str] = list(command)
        self._error: type[ProcessError] = error
        self._process: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._lock: threading.Lock = threading.Lock()

    def run(self, code: str, timeout: float) -> str:
        """Return what the code printed; the error class with its traceback when it raised, ShellGoneError otherwise."""
        with self._lock:
            try:
                answer = self._exchange(json.dumps({"code": code}), timeout)
            except ShellGoneError:
                self.close()
                raise
        found = json.loads(answer)
        if found["error"]:
            raise self._error(self.command, str(found["error"]))
        return str(found["out"])

    def close(self) -> None:
        """Stop the shell; the next run starts a new one."""
        if self._process is not None:
            self._process.kill()
            self._process = None
            self._lines = queue.Queue()

    def _exchange(self, request: str, timeout: float) -> str:
        process = self._started()
        try:
            _send(cast("IO[str]", process.stdin), request)
        except OSError as error:
            raise ShellGoneError(str(error)) from error
        return self._answer(timeout)

    def _started(self) -> subprocess.Popen[str]:
        if self._process is None or self._process.poll() is not None:
            self._process = start_process(self.command, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            threading.Thread(target=_read, args=(self._process, self._lines), daemon=True).start()
        return self._process

    def _answer(self, timeout: float) -> str:
        """Return the next RESPONSE line's JSON; the shell's other output (Django's chatter, logs) is skipped."""
        while True:
            try:
                line = self._lines.get(timeout=timeout)
            except queue.Empty as error:
                msg = f"no answer in {timeout:g} s"
                raise ShellGoneError(msg) from error
            if line is None:
                msg = "the shell ended"
                raise ShellGoneError(msg)
            if line.startswith(RESPONSE):
                return line.removeprefix(RESPONSE)


def _send(stdin: IO[str], request: str) -> None:
    stdin.write(f"{request}\n")
    stdin.flush()


def _read(process: subprocess.Popen[str], lines: queue.Queue[str | None]) -> None:
    """Put the shell's output lines on the queue, then None when it ends."""
    for line in cast("IO[str]", process.stdout):
        lines.put(line.rstrip("\n"))
    lines.put(None)
