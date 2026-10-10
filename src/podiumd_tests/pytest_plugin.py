"""Fixtures and markers for the environment tests (tests/), loaded by tests/conftest.py.

Fixture functions are named fixture_<name> and registered with name=<name>,
so tests that request them do not shadow a module-level function.
"""

from __future__ import annotations

import functools

from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests import results
from podiumd_tests.bootstrap import bootstrap
from podiumd_tests.bootstrap import check
from podiumd_tests.bootstrap import refusal
from podiumd_tests.bootstrap.names import PRODUCTAANVRAAG_OBJECTTYPE
from podiumd_tests.bootstrap.names import TEST_ZAAKTYPE
from podiumd_tests.bootstrap.names import ZGW_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_NOAUTH_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_NOAUTH_STORE_KEY
from podiumd_tests.bootstrap.names import ZGW_OPENBAAR_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_OPENBAAR_STORE_KEY
from podiumd_tests.bootstrap.names import ZGW_PRODUCTAANVRAAG_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_PRODUCTAANVRAAG_STORE_KEY
from podiumd_tests.bootstrap.names import ZGW_STORE_KEY
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.steps import STEPS
from podiumd_tests.clients.platform import mailpit_client
from podiumd_tests.clients.platform import objecten_client
from podiumd_tests.clients.platform import objecttypen_client
from podiumd_tests.clients.platform import openklant_client
from podiumd_tests.clients.platform import opennotificaties_client
from podiumd_tests.clients.platform import openzaak_client
from podiumd_tests.config import default_envs_dir
from podiumd_tests.config import load_profile
from podiumd_tests.environment import Environment
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import ZaaktypeParts
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.seed.openzaak import zaaktype_parts
from podiumd_tests.seed.registry import ResourceRegistry
from podiumd_tests.webhook import Callback
from podiumd_tests.zac import confirmation_on
from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import zaakafhandelparameters
from podiumd_tests.zac import zac_session

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator
    from collections.abc import Sequence

    import requests

    from _pytest.mark.structures import ParameterSet  # pytest.param's type; pytest has no public name for it

    from podiumd_tests.capabilities import Capabilities
    from podiumd_tests.clients.api import ApiClient
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
    group.addoption("--perf-users", type=int, default=5, help="Locust users in the perf tier (default 5)")
    # 60 s: a single stall of a one-process app (a uWSGI worker restart) then stays below the p95.
    group.addoption("--perf-duration", default="60s", help="duration of the perf tier's Locust run (default 60s)")
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
        outcomes = check(podiumd_env, wanted)
        skipped = [o for o in outcomes if o.action == "skipped"]
        if skipped:  # e.g. wiring off for the profile, or the component is absent
            pytest.skip("; ".join(f"bootstrap step {o.step}: {o.detail}" for o in skipped))
        missing = [s for s, o in zip(wanted, outcomes, strict=True) if o.action != "present"]
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
    return openklant_client(podiumd_env)


@pytest.fixture(scope="session", name="objecten")
def fixture_objecten(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> ApiClient:
    """Objecten API with the suite's own token (bootstrap step objecten-token)."""
    need_bootstrap("objecten-token")
    return objecten_client(podiumd_env)


@pytest.fixture(scope="session", name="objecttypen")
def fixture_objecttypen(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> ApiClient:
    """Objecttypen API with the suite's own token (bootstrap step objecttypen-token)."""
    need_bootstrap("objecttypen-token")
    return objecttypen_client(podiumd_env)


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
    return openzaak_client(podiumd_env, client_id, key, run_tag, _CURRENT_TEST.get)


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


@pytest.fixture(scope="session", name="openzaak_productaanvraag")
def fixture_openzaak_productaanvraag(
    run_tag: str, podiumd_env: Environment, need_bootstrap: Callable[..., None]
) -> ApiClient:
    """Open Zaak as the client that may only read and delete zaken of the productaanvraag zaaktype."""
    return _zgw_client(
        run_tag,
        podiumd_env,
        need_bootstrap,
        "openzaak-client-productaanvraag",
        ZGW_PRODUCTAANVRAAG_CLIENT_ID,
        ZGW_PRODUCTAANVRAAG_STORE_KEY,
    )


@pytest.fixture(scope="session", name="opennotificaties")
def fixture_opennotificaties(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> ApiClient:
    """Open Notificaties as the suite's own client ptest-bootstrap-nrc."""
    need_bootstrap("opennotificaties-client")
    return opennotificaties_client(podiumd_env)


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


@pytest.fixture(scope="session", name="mailpit")
def fixture_mailpit(podiumd_env: Environment) -> ApiClient:
    """The environment's Mailpit API."""
    return mailpit_client(podiumd_env)


@pytest.fixture(scope="session", name="pabc_api_key")
def fixture_pabc_api_key(credentials: SecretResolver) -> str:
    """PABC's API key (secret pabc_api_key); skips when the profile has none."""
    key = credentials.optional("pabc_api_key")
    if not key:
        pytest.skip("no secret pabc_api_key in the profile")
    return key


@pytest.fixture(name="new_callback")
def fixture_new_callback(
    run_tag: str, podiumd_env: Environment, need_bootstrap: Callable[..., None]
) -> Callable[..., Callback]:
    """Makes callback paths of this test's own on the webhook receiver (infra/webhook-receiver); takes fail_first."""
    need_bootstrap("infra-webhook-receiver")
    return functools.partial(Callback.new, podiumd_env, run_tag)


@pytest.fixture(name="callback")
def fixture_callback(new_callback: Callable[..., Callback]) -> Callback:
    """A callback path of this test's own on the webhook receiver."""
    return new_callback()


@pytest.fixture(scope="session", name="productaanvraagtype")
def fixture_productaanvraagtype(podiumd_env: Environment) -> str:
    """The productaanvraagtype ZAC starts zaken for (profile setting productaanvraag_type); skips without it."""
    found = podiumd_env.profile.settings.get("productaanvraag_type")
    if not found:
        pytest.skip(f"profile {podiumd_env.profile.name} has no settings.productaanvraag_type")
    return found


@pytest.fixture(scope="session", name="productaanvraag_objecttype")
def fixture_productaanvraag_objecttype(podiumd_env: Environment) -> str:
    """The productaanvraag objecttype's URL as Objecten knows it."""
    return objecttype_url(podiumd_env, PRODUCTAANVRAAG_OBJECTTYPE)


@pytest.fixture(name="ontvangstbevestiging")
def fixture_ontvangstbevestiging(
    zac: requests.Session, podiumd_env: Environment, need_bootstrap: Callable[..., None]
) -> None:
    """Skips unless ZAC mails an ontvangstbevestiging for productaanvragen (of setting productaanvraag_zaaktype)."""
    need_bootstrap("zac-email-confirmation")
    zaaktype = str(podiumd_env.profile.settings.get("productaanvraag_zaaktype"))
    if not confirmation_on(zac, podiumd_env.profile.urls["zac"], zaaktype):
        pytest.skip(
            f"ZAC sends no ontvangstbevestiging for {zaaktype}: allow it with profile setting zac_email_confirmation"
        )


@pytest.fixture(name="zac")
def fixture_zac(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> requests.Session:
    """The test admin's session on ZAC's REST API."""
    need_bootstrap(ADMIN.name)
    return zac_session(podiumd_env, ADMIN.username, podiumd_env.credentials.get(ADMIN.store_key))


@pytest.fixture(name="zac_parameters")
def fixture_zac_parameters(zac: requests.Session, urls: dict[str, str], podiumd_env: Environment) -> JsonObject:
    """ZAC's zaakafhandelparameters of the zaaktype ZAC starts zaken of (profile setting productaanvraag_zaaktype)."""
    identificatie = podiumd_env.profile.settings.get("productaanvraag_zaaktype")
    if not identificatie:
        pytest.skip(f"profile {podiumd_env.profile.name} has no settings.productaanvraag_zaaktype")
    found = zaakafhandelparameters(zac, urls["zac"], identificatie)
    if not found:
        pytest.skip(f"ZAC has no zaakafhandelparameters for {identificatie}")
    return found[0]


@pytest.fixture(name="zac_zaak")
def fixture_zac_zaak(
    zac: requests.Session,
    urls: dict[str, str],
    zac_parameters: JsonObject,
    openzaak_productaanvraag: ApiClient,
    registry: ResourceRegistry,
) -> Callable[..., JsonObject]:
    """Start a zaak in ZAC with a run-tagged omschrijving; cleanup deletes it from Open Zaak."""

    def start(**fields: object) -> JsonObject:
        zaak = create_zaak(zac, urls["zac"], zac_parameters, omschrijving=registry.tagged("zac-zaak"), **fields)
        url = f"{urls['openzaak']}/{ZAKEN}/zaken/{zaak['uuid']}"
        registry.add(
            f"zaak {zaak['identificatie']}",
            lambda: delete_zaak(openzaak_productaanvraag, url, with_documents=True),
        )
        return zaak

    return start


@pytest.hookimpl(tryfirst=True)  # before xdist reads the groups
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Put the destructive tests in one xdist group: each disturbs state the others use."""
    for item in items:
        if item.get_closest_marker("destructive"):
            item.add_marker(pytest.mark.xdist_group("destructive"))


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


def requiring(
    component: str, *values: object, test_id: str | None = None, marks: Sequence[pytest.MarkDecorator] = ()
) -> ParameterSet:
    """A pytest.param with these values that skips unless the environment has the component; marks add to that.

    For tests parametrized per component, e.g. [requiring(c, c) for c in COMPONENTS].
    """
    return pytest.param(*values, id=test_id or component, marks=[pytest.mark.requires(component), *marks])
