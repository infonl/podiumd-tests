"""Unit tests for the pytest plugin, run in a nested pytest session (pytester)."""

from podiumd_tests.pytest_plugin import requiring

pytest_plugins = ["pytester"]

INNER_CONFTEST = """
import subprocess

from podiumd_tests.config import parse_profile
from podiumd_tests.environment import Environment
from podiumd_tests.pytest_plugin import ENVIRONMENT_KEY

pytest_plugins = ["podiumd_tests.pytest_plugin"]


def no_cluster(args, _timeout, _stdin=None):
    return subprocess.CompletedProcess(list(args), 1, "", "no cluster")


def pytest_configure(config):
    profile = parse_profile(
        {
            "estate": "podiumd-infra",
            "allowed_tiers": ["smoke"],
            "kube": {"context": "ctx", "namespace": "podiumd"},
            "urls": {"openzaak": "https://openzaak.example.test"},
        },
        name="inner",
    )
    config.stash[ENVIRONMENT_KEY] = Environment(profile, no_cluster, environ={})
"""

INNER_TESTS = """
import pytest


@pytest.fixture(scope="module")
def zac_client():
    raise AssertionError("module fixture ran for a skipped test")


@pytest.mark.requires("zac")
def test_needs_zac(zac_client):
    pass


@pytest.mark.requires("openzaak")
def test_needs_openzaak():
    pass


@pytest.mark.requires("cluster")
def test_needs_cluster():
    pass
"""


def test_requires_skips_before_module_fixtures_run(pytester):
    pytester.makeconftest(INNER_CONFTEST)
    pytester.makepyfile(INNER_TESTS)
    # pytest-playwright does not support a nested in-process session; the markers live in pyproject.toml.
    result = pytester.runpytest_inprocess("-rs", "-p", "no:playwright", "-W", "ignore::pytest.PytestUnknownMarkWarning")
    result.assert_outcomes(passed=1, skipped=2)
    result.stdout.fnmatch_lines(["*requires: zac (no URL in profile)*", "*requires: cluster (kube API of context ctx*"])
    result.stdout.no_fnmatch_line("*module fixture ran*")


def test_requiring_builds_a_param_that_requires_its_component():
    param = requiring("kiss", "kiss", "/healthz", test_id="kiss/healthz")
    assert param.values == ("kiss", "/healthz")
    assert param.id == "kiss/healthz"
    assert [(m.name, m.args) for m in param.marks] == [("requires", ("kiss",))]


def test_destructive_tests_share_one_xdist_group(pytester):
    pytester.makeconftest(INNER_CONFTEST)
    pytester.makepyfile(
        """
import pytest


@pytest.mark.destructive
def test_destructive(request):
    assert request.node.get_closest_marker("xdist_group").args == ("destructive",)


def test_other(request):
    assert request.node.get_closest_marker("xdist_group") is None
"""
    )
    result = pytester.runpytest_inprocess("-p", "no:playwright", "-W", "ignore::pytest.PytestUnknownMarkWarning")
    result.assert_outcomes(passed=2)
