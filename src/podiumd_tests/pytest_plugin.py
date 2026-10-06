"""Fixtures and markers for the environment tests (tests/), loaded by tests/conftest.py.

Fixture functions are named fixture_<name> and registered with name=<name>,
so tests that request them do not shadow a module-level function.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests import results
from podiumd_tests.bootstrap import bootstrap
from podiumd_tests.bootstrap import check
from podiumd_tests.bootstrap import refusal
from podiumd_tests.bootstrap.steps import STEPS
from podiumd_tests.config import default_envs_dir
from podiumd_tests.config import load_profile
from podiumd_tests.environment import Environment
from podiumd_tests.seed.registry import ResourceRegistry

if TYPE_CHECKING:
    from collections.abc import Iterator

    import requests

    from _pytest.mark.structures import ParameterSet  # pytest.param's type; pytest has no public name for it

    from podiumd_tests.capabilities import Capabilities
    from podiumd_tests.credentials import SecretResolver
    from podiumd_tests.kube import Kube


def pytest_addoption(parser: pytest.Parser) -> None:
    """Command-line options; `podiumd-tests run` passes them."""
    group = parser.getgroup("podiumd")
    group.addoption("--podiumd-env", help="environment profile name (envs/**/<name>.yaml)")
    group.addoption("--podiumd-envs-dir", default=str(default_envs_dir()))
    group.addoption("--podiumd-run-tag", help="tag for created resources (default: ptest-<random>)")
    group.addoption("--keep-data", action="store_true", help="skip cleanup of created resources")
    group.addoption("--auto-bootstrap", action="store_true", help="apply missing bootstrap steps instead of failing")


ENVIRONMENT_KEY = pytest.StashKey[Environment]()


def _environment(config: pytest.Config) -> Environment:
    """The environment under test, from --podiumd-env; built once per run."""
    if ENVIRONMENT_KEY not in config.stash:
        name: str | None = config.getoption("--podiumd-env")
        if not name:
            pytest.exit("no environment: use `podiumd-tests run --env <name>` or pass --podiumd-env", returncode=2)
        profile = load_profile(name, Path(str(config.getoption("--podiumd-envs-dir"))))
        config.stash[ENVIRONMENT_KEY] = Environment(profile)
    return config.stash[ENVIRONMENT_KEY]


@pytest.fixture(scope="session", name="podiumd_env")
def fixture_podiumd_env(request: pytest.FixtureRequest) -> Environment:
    """The environment under test, from --podiumd-env."""
    return _environment(request.config)


@pytest.fixture(scope="session", name="kube")
def fixture_kube(podiumd_env: Environment) -> Kube:
    """kubectl bound to the environment's context and namespace."""
    return podiumd_env.kube


@pytest.fixture(scope="session", name="credentials")
def fixture_credentials(podiumd_env: Environment) -> SecretResolver:
    """Secrets of the environment, resolved on first use."""
    return podiumd_env.credentials


@pytest.fixture(scope="session", name="caps")
def fixture_caps(podiumd_env: Environment) -> Capabilities:
    """Detected capabilities of the environment."""
    return podiumd_env.capabilities


@pytest.fixture(scope="session", name="urls")
def fixture_urls(podiumd_env: Environment) -> dict[str, str]:
    """Base URL per component."""
    return podiumd_env.profile.urls


@pytest.fixture(scope="session", name="http")
def fixture_http(podiumd_env: Environment) -> Iterator[requests.Session]:
    """HTTP session that reaches the profile URLs (also in host-header mode)."""
    session = podiumd_env.session()
    yield session
    session.close()


@pytest.fixture(scope="session", name="run_tag")
def fixture_run_tag(request: pytest.FixtureRequest) -> str:
    """Tag carried by every created resource (PLAN.md R9)."""
    return str(request.config.getoption("--podiumd-run-tag") or results.run_tag(results.new_run_id()))


@pytest.fixture(scope="session", name="bootstrap_ok")
def fixture_bootstrap_ok(request: pytest.FixtureRequest, podiumd_env: Environment) -> None:
    """Fail fast when bootstrap is missing; with --auto-bootstrap, apply it (PLAN.md §4 A)."""
    missing = [o.step for o in check(podiumd_env, STEPS) if o.action == "missing"]
    if not missing:
        return
    name = podiumd_env.profile.name
    if not request.config.getoption("--auto-bootstrap"):
        pytest.fail(f"bootstrap missing on {name} ({', '.join(missing)}): run `podiumd-tests bootstrap --env {name}`")
    reason = refusal(podiumd_env.profile)
    if reason:
        pytest.fail(f"--auto-bootstrap refused: {reason}")
    bootstrap(podiumd_env, STEPS)


@pytest.fixture(name="registry")
def fixture_registry(request: pytest.FixtureRequest, run_tag: str) -> Iterator[ResourceRegistry]:
    """Per-test cleanup: deleters run in reverse order after the test, also when it failed."""
    reg = ResourceRegistry(run_tag, keep=bool(request.config.getoption("--keep-data")))
    yield reg
    kept = reg.cleanup()
    if kept:
        print(f"--keep-data: left behind {', '.join(kept)}")


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip tests whose @pytest.mark.requires(...) capabilities are absent.

    A hook rather than an autouse fixture: it runs before any fixture, also
    before module- or session-scoped ones that would need the capability.
    """
    needed = [str(c) for m in item.iter_markers("requires") for c in cast("tuple[object, ...]", m.args)]
    if needed:
        reason = _environment(item.config).capabilities.skip_reason(*needed)
        if reason:
            pytest.skip(reason)


def requiring(component: str, *values: object, test_id: str | None = None) -> ParameterSet:
    """A pytest.param with these values that skips unless the environment has the component.

    For tests parametrized per component, e.g. [requiring(c, c) for c in COMPONENTS].
    """
    return pytest.param(*values, id=test_id or component, marks=pytest.mark.requires(component))
