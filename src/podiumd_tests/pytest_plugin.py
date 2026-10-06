"""Fixtures and markers for the environment tests (tests/), loaded by tests/conftest.py.

Fixture functions are named fixture_<name> and registered with name=<name>,
so tests that request them do not shadow a module-level function.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.config import default_envs_dir
from podiumd_tests.config import load_profile
from podiumd_tests.environment import Environment
from podiumd_tests.results import new_run_id
from podiumd_tests.seed.registry import ResourceRegistry

if TYPE_CHECKING:
    from collections.abc import Iterator

    import requests

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


@pytest.fixture(scope="session", name="podiumd_env")
def fixture_podiumd_env(request: pytest.FixtureRequest) -> Environment:
    """The environment under test, from --podiumd-env."""
    name: str | None = request.config.getoption("--podiumd-env")
    if not name:
        pytest.exit("no environment: use `podiumd-tests run --env <name>` or pass --podiumd-env", returncode=2)
    profile = load_profile(name, Path(str(request.config.getoption("--podiumd-envs-dir"))))
    return Environment(profile)


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
    return str(request.config.getoption("--podiumd-run-tag") or f"ptest-{new_run_id()}")


@pytest.fixture(name="registry")
def fixture_registry(request: pytest.FixtureRequest, run_tag: str) -> Iterator[ResourceRegistry]:
    """Per-test cleanup: deleters run in reverse order after the test, also when it failed."""
    reg = ResourceRegistry(run_tag, keep=bool(request.config.getoption("--keep-data")))
    yield reg
    kept = reg.cleanup()
    if kept:
        print(f"--keep-data: left behind {', '.join(kept)}")


@pytest.fixture(autouse=True, name="_requires")
def fixture_requires(request: pytest.FixtureRequest) -> None:
    """Skip tests whose @pytest.mark.requires(...) capabilities are absent."""
    node = cast("pytest.Item", request.node)
    needed = [str(c) for m in node.iter_markers("requires") for c in cast("tuple[object, ...]", m.args)]
    if needed:
        capabilities: Capabilities = request.getfixturevalue("caps")
        reason = capabilities.skip_reason(*needed)
        if reason:
            pytest.skip(reason)
