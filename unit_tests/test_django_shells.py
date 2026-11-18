"""Unit tests for the long-lived Django shell: its protocol, errors and restart, with a local Python as the shell."""

import sys

import pytest

from podiumd_tests.django_shells import SERVER
from podiumd_tests.django_shells import DjangoShell
from podiumd_tests.django_shells import ShellGoneError
from podiumd_tests.kube import Kube
from podiumd_tests.process import ProcessError

# SERVER without Django: closing the database connections is the only Django call.
LOCAL = SERVER.replace("from django import db", "").replace("db.connections.close_all()", "pass")


@pytest.fixture(name="shell")
def fixture_shell():
    shell = DjangoShell([sys.executable, "-c", f"print('chatter')\n{LOCAL}"])
    yield shell
    shell.close()


def test_each_request_runs_in_a_fresh_child_and_returns_what_it_printed(shell):
    assert shell.run("x = 1\nprint('PTEST_VALUE=1')", 10) == "PTEST_VALUE=1\n"
    # The child's x is gone: the next request starts from the shell's own state.
    assert shell.run("print('x' in globals())", 10) == "False\n"


def test_an_exception_is_the_error_with_its_traceback_and_the_shell_lives_on(shell):
    with pytest.raises(ProcessError, match="ValueError: bad"):
        shell.run("raise ValueError('bad')", 10)
    assert shell.run("print(2)", 10) == "2\n"


def test_a_shell_that_ends_is_gone_and_starts_again(shell):
    with pytest.raises(ShellGoneError):
        shell.run("import os; os.kill(os.getppid(), 9)", 10)
    assert shell.run("print(3)", 10) == "3\n"


def test_kube_falls_back_to_a_one_shot_shell_when_the_long_lived_one_is_gone(fake_runner, monkeypatch):
    def gone(*_args):
        msg = "no answer"
        raise ShellGoneError(msg)

    monkeypatch.setattr(DjangoShell, "run", gone)
    fake_runner.answers["exec -i deploy/openzaak"] = (0, "PTEST_VALUE=1\n")
    kube = Kube("ctx", "ns", fake_runner)
    with kube.shells_kept():
        assert kube.exec_django_shell("openzaak", "print(1)") == "PTEST_VALUE=1\n"
    assert kube.long_lived_shells is False
