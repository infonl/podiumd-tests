"""Fixtures and markers for the environment tests (tests/), loaded by tests/conftest.py.

Fixture functions are named fixture_<name> and registered with name=<name>,
so tests that request them do not shadow a module-level function.
"""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests import results
from podiumd_tests.auth.zgw_jwt import zgw_headers
from podiumd_tests.auth.zgw_jwt import zgw_jwt
from podiumd_tests.bootstrap import bootstrap
from podiumd_tests.bootstrap import check
from podiumd_tests.bootstrap import refusal
from podiumd_tests.bootstrap.steps import OPENKLANT_STORE_KEY
from podiumd_tests.bootstrap.steps import STEPS
from podiumd_tests.bootstrap.steps import TEST_ZAAKTYPE
from podiumd_tests.bootstrap.steps import ZGW_CLIENT_ID
from podiumd_tests.bootstrap.steps import ZGW_NOAUTH_CLIENT_ID
from podiumd_tests.bootstrap.steps import ZGW_NOAUTH_STORE_KEY
from podiumd_tests.bootstrap.steps import ZGW_OPENBAAR_CLIENT_ID
from podiumd_tests.bootstrap.steps import ZGW_OPENBAAR_STORE_KEY
from podiumd_tests.bootstrap.steps import ZGW_STORE_KEY
from podiumd_tests.clients.api import ApiClient
from podiumd_tests.config import default_envs_dir
from podiumd_tests.config import load_profile
from podiumd_tests.environment import Environment
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import ZaaktypeParts
from podiumd_tests.seed.openzaak import zaaktype_parts
from podiumd_tests.seed.registry import ResourceRegistry

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator

    import requests

    from _pytest.mark.structures import ParameterSet  # pytest.param's type; pytest has no public name for it

    from podiumd_tests.capabilities import Capabilities
    from podiumd_tests.credentials import SecretResolver
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.kube import Kube


def pytest_addoption(parser: pytest.Parser) -> None:
    """Command-line options; `podiumd-tests run` passes them."""
    group = parser.getgroup("podiumd")
    group.addoption("--podiumd-env", help="environment profile name (envs/**/<name>.yaml)")
    group.addoption("--podiumd-envs-dir", default=str(default_envs_dir()), help="profile directory (default: envs/)")
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


@pytest.fixture(scope="session", name="need_bootstrap")
def fixture_need_bootstrap(request: pytest.FixtureRequest, podiumd_env: Environment) -> Callable[..., None]:
    """need(*step_names): fail fast when those bootstrap steps are missing (PLAN.md §4 A).

    Each step is checked once per session. With --auto-bootstrap the missing ones are applied.
    """
    checked: set[str] = set()
    auto = bool(request.config.getoption("--auto-bootstrap"))

    def need(*names: str) -> None:
        wanted = [s for s in STEPS if s.name in names and s.name not in checked]
        unknown = set(names) - {s.name for s in STEPS}
        if unknown:
            pytest.fail(f"unknown bootstrap steps: {', '.join(sorted(unknown))}")
        missing = [s for s, o in zip(wanted, check(podiumd_env, wanted), strict=True) if o.action != "present"]
        name = podiumd_env.profile.name
        if missing and not auto:
            steps = ", ".join(s.name for s in missing)
            pytest.fail(f"bootstrap missing on {name} ({steps}): run `podiumd-tests bootstrap --env {name}`")
        if missing:
            reason = refusal(podiumd_env.profile)
            if reason:
                pytest.fail(f"--auto-bootstrap refused: {reason}")
            failed_steps = [o for o in bootstrap(podiumd_env, missing) if o.action != "created"]
            if failed_steps:
                pytest.fail("--auto-bootstrap: " + "; ".join(f"{o.step} {o.action}: {o.detail}" for o in failed_steps))
        checked.update(s.name for s in wanted)

    return need


@pytest.fixture(scope="session", name="openklant")
def fixture_openklant(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> ApiClient:
    """Open Klant klantinteracties API with the suite's own token (bootstrap step openklant-token)."""
    need_bootstrap("openklant-token")
    token = podiumd_env.credentials.get(OPENKLANT_STORE_KEY)
    url = podiumd_env.profile.urls["openklant"] + "/klantinteracties/api/v1"
    return ApiClient(podiumd_env.session(cookies=False), url, {"Authorization": f"Token {token}"})


# The test running now; Open Zaak writes it into its audittrail through X-Audit-Toelichting.
_CURRENT_TEST: ContextVar[str] = ContextVar("current_test", default="")


@pytest.fixture(autouse=True, name="_current_test")
def fixture_current_test(request: pytest.FixtureRequest) -> Iterator[None]:
    """Make the running test's node id available to the API clients."""
    token = _CURRENT_TEST.set(cast("pytest.Item", request.node).nodeid)
    yield
    _CURRENT_TEST.reset(token)


def _zgw_client(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixture plumbing
    run_tag: str, podiumd_env: Environment, need_bootstrap: Callable[..., None], step: str, client_id: str, key: str
) -> ApiClient:
    need_bootstrap(step)
    secret = podiumd_env.credentials.get(key)

    def headers() -> dict[str, str]:
        # Each change in Open Zaak's audittrail then names the run and the test that made it.
        token = zgw_jwt(client_id, secret, user=f"podiumd-tests {run_tag}")
        return {**zgw_headers(token), "X-Audit-Toelichting": f"{run_tag} {_CURRENT_TEST.get()}"[:255]}

    return ApiClient(podiumd_env.session(cookies=False), podiumd_env.profile.urls["openzaak"], headers)


@pytest.fixture(scope="session", name="openzaak")
def fixture_openzaak(run_tag: str, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> ApiClient:
    """Open Zaak's ZGW APIs as the suite's own client, with a fresh token per request."""
    return _zgw_client(run_tag, podiumd_env, need_bootstrap, "openzaak-client", ZGW_CLIENT_ID, ZGW_STORE_KEY)


@pytest.fixture(scope="session", name="zgw_secret")
def fixture_zgw_secret(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> str:
    """The secret of the suite's own ZGW client, for tests that build their own tokens."""
    need_bootstrap("openzaak-client")
    return podiumd_env.credentials.get(ZGW_STORE_KEY)


@pytest.fixture(scope="session", name="openzaak_openbaar")
def fixture_openzaak_openbaar(run_tag: str, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> ApiClient:
    """Open Zaak as a client that sees vertrouwelijkheid openbaar at most and cannot delete."""
    return _zgw_client(
        run_tag, podiumd_env, need_bootstrap, "openzaak-client-openbaar", ZGW_OPENBAAR_CLIENT_ID, ZGW_OPENBAAR_STORE_KEY
    )


@pytest.fixture(scope="session", name="openzaak_noauth")
def fixture_openzaak_noauth(run_tag: str, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> ApiClient:
    """Open Zaak as a known client without any autorisatie."""
    return _zgw_client(
        run_tag, podiumd_env, need_bootstrap, "openzaak-client-noauth", ZGW_NOAUTH_CLIENT_ID, ZGW_NOAUTH_STORE_KEY
    )


@pytest.fixture(scope="session", name="test_zaaktype")
def fixture_test_zaaktype(openzaak: ApiClient, need_bootstrap: Callable[..., None]) -> JsonObject:
    """The published test zaaktype in the test catalogus (bootstrap step openzaak-zaaktype)."""
    need_bootstrap("openzaak-zaaktype")
    found = openzaak.list(f"{CATALOGI}/zaaktypen", {"identificatie": TEST_ZAAKTYPE})
    return found[0]


@pytest.fixture(scope="session", name="parts")
def fixture_parts(openzaak: ApiClient, test_zaaktype: JsonObject) -> ZaaktypeParts:
    """The statustypen, roltypen and other types of the test zaaktype."""
    return zaaktype_parts(openzaak, test_zaaktype)


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
