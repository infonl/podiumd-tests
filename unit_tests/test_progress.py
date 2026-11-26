"""Unit tests for the progress file, run in a nested pytest session (pytester)."""

from podiumd_tests.progress import Progress

pytest_plugins = ["pytester"]

INNER_TESTS = """
import pytest


@pytest.fixture
def broken_teardown():
    yield
    raise AssertionError("teardown")


@pytest.fixture
def broken_setup():
    raise AssertionError("setup")


def test_passes():
    pass


def test_fails():
    assert False


@pytest.mark.skip(reason="not here")
def test_skipped():
    pass


@pytest.mark.xfail(reason="known", strict=True)
def test_xfails():
    assert False


@pytest.mark.xfail(reason="intermittent", strict=False)
def test_xpasses():
    pass


def test_setup_error(broken_setup):
    pass


def test_teardown_error(broken_teardown):
    pass
"""


def test_progress_writes_one_line_per_finished_test(pytester):
    pytester.makepyfile(test_inner=INNER_TESTS)
    path = pytester.path / "progress.log"

    pytester.runpytest_inprocess("-p", "no:playwright", plugins=[Progress(path, lambda: "12:00:00")])

    lines = [line.rsplit(" (", 1)[0] for line in path.read_text(encoding="utf-8").splitlines()]
    assert lines == [
        "12:00:00 collected 7 tests",
        "12:00:00 1/7 passed test_inner.py::test_passes",
        "12:00:00 2/7 failed test_inner.py::test_fails",
        "12:00:00 3/7 skipped test_inner.py::test_skipped",
        "12:00:00 4/7 xfailed test_inner.py::test_xfails",
        "12:00:00 5/7 xpassed test_inner.py::test_xpasses",
        "12:00:00 6/7 error test_inner.py::test_setup_error",
        "12:00:00 7/7 passed test_inner.py::test_teardown_error",
        "12:00:00 7/7 error in teardown test_inner.py::test_teardown_error",
    ]
