"""Fixtures and markers for the environment tests (tests/), loaded by tests/conftest.py.

Fixture functions are named fixture_<name> and registered with name=<name>,
so tests that request them do not shadow a module-level function.
"""

from __future__ import annotations

import functools

from contextvars import ContextVar
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests import replicas
from podiumd_tests import results
from podiumd_tests import scenarios
from podiumd_tests.bootstrap import names
from podiumd_tests.bootstrap import runner
from podiumd_tests.bootstrap import steps
from podiumd_tests.bootstrap.bpmn import uuid_of
from podiumd_tests.clients import platform
from podiumd_tests.config import default_envs_dir
from podiumd_tests.config import load_profile
from podiumd_tests.environment import Environment
from podiumd_tests.kube import cluster_service
from podiumd_tests.mock_server import Callback
from podiumd_tests.oidc import challenge_session
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openzaak import ZaaktypeParts
from podiumd_tests.seed.openzaak import published_zaaktype
from podiumd_tests.seed.openzaak import zaaktype_parts
from podiumd_tests.seed.registry import ResourceRegistry
from podiumd_tests.seed.zac_zaaktype import zac_as_admin
from podiumd_tests.sources import source_problems
from podiumd_tests.sources import sources
from podiumd_tests.workloads import skip_older_than
from podiumd_tests.zac import clean_up_zaak
from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import is_confirmation_on
from podiumd_tests.zac import user_groups
from podiumd_tests.zac import zaakafhandelparameters
from podiumd_tests.zac import zac_session

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Generator
    from collections.abc import Iterator
    from collections.abc import Sequence

    import requests

    from _pytest.mark.structures import ParameterSet  # pytest.param's type; pytest has no public name for it

    from podiumd_tests.bootstrap.keycloak import KeycloakUser
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
    """Return the environment under test, from --podiumd-env; built once per run."""
    if ENVIRONMENT_KEY not in config.stash:
        name: str | None = config.getoption("--podiumd-env")
        if not name:
            pytest.exit("no environment: use `podiumd-tests run --env <name>` or pass --podiumd-env", returncode=2)
        profile = load_profile(name, Path(str(config.getoption("--podiumd-envs-dir"))))
        config.stash[ENVIRONMENT_KEY] = Environment(profile)
    return config.stash[ENVIRONMENT_KEY]


@pytest.fixture(scope="session", name="podiumd_env")
def fixture_podiumd_env(request: pytest.FixtureRequest) -> Environment:
    """Return the environment under test, from --podiumd-env."""
    return _environment(request.config)


@pytest.fixture(scope="session", name="several_replicas")
def fixture_several_replicas(podiumd_env: Environment) -> Generator[None]:
    """Several pods of redis-ha and Keycloak for the whole session (profile setting replicas_command)."""
    with replicas.several_replicas(podiumd_env):
        yield


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
    """Return the detected capabilities of the environment."""
    return podiumd_env.capabilities


@pytest.fixture(scope="session", name="urls")
def fixture_urls(podiumd_env: Environment) -> Iterator[dict[str, str]]:
    """Yield the base URL per component, as this console reaches it."""
    with podiumd_env.console_urls() as urls:
        yield urls


@pytest.fixture(scope="session", name="http")
def fixture_http(podiumd_env: Environment) -> Iterator[requests.Session]:
    """HTTP session that reaches the profile URLs (also in host-header mode)."""
    session = podiumd_env.session()
    yield session
    session.close()


@pytest.fixture(scope="session", name="run_tag")
def fixture_run_tag(request: pytest.FixtureRequest) -> str:
    """Tag carried by every created resource."""
    return str(request.config.getoption("--podiumd-run-tag") or results.run_tag(results.new_run_id()))


@pytest.fixture(scope="session", name="run_dir")
def fixture_run_dir(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Return a directory that every pytest-xdist worker of this run shares."""
    base = tmp_path_factory.getbasetemp()
    return base.parent if hasattr(request.config, "workerinput") else base


def _missing(env: Environment, wanted: list[runner.Step]) -> list[runner.Step]:
    """Return the wanted steps that are not in place; skips the test when check skips one."""
    outcomes = runner.check(env, wanted)
    skipped = [outcome for outcome in outcomes if outcome.action == "skipped"]
    if skipped:  # e.g. wiring off for the profile, or the component is absent
        pytest.skip("; ".join(f"bootstrap step {outcome.step}: {outcome.detail}" for outcome in skipped))
    return [step for step, outcome in zip(wanted, outcomes, strict=True) if outcome.action != "present"]


def _auto_bootstrap(env: Environment, missing: list[runner.Step]) -> None:
    """Apply the missing steps (--auto-bootstrap); fails the test when bootstrap is refused or a step fails."""
    reason = runner.refusal(env.profile)
    if reason:
        pytest.fail(f"--auto-bootstrap refused: {reason}")
    failed_steps = [outcome for outcome in runner.bootstrap(env, missing) if outcome.action != "created"]
    if failed_steps:
        failures = "; ".join(f"{outcome.step} {outcome.action}: {outcome.detail}" for outcome in failed_steps)
        pytest.fail(f"--auto-bootstrap: {failures}")


@pytest.fixture(scope="session", name="need_bootstrap")
def fixture_need_bootstrap(
    request: pytest.FixtureRequest, run_dir: Path, podiumd_env: Environment
) -> Callable[..., None]:
    """need(*step_names): fail fast when those bootstrap steps are missing.

    A step found present is not checked again in this run, also not by other pytest-xdist workers.
    With --auto-bootstrap the missing ones are applied.
    """
    auto = bool(request.config.getoption("--auto-bootstrap"))
    present = run_dir / "bootstrap-present"
    present.mkdir(exist_ok=True)

    def need(*step_names: str) -> None:
        named = [step for step in steps.STEPS if step.name in step_names]
        wanted = [step for step in named if not (present / step.name).exists()]
        unknown = set(step_names) - {step.name for step in named}
        if unknown:
            pytest.fail(f"unknown bootstrap steps: {', '.join(sorted(unknown))}")
        missing = _missing(podiumd_env, wanted)
        name = podiumd_env.profile.name
        if missing and not auto:
            missing_names = ", ".join(step.name for step in missing)
            pytest.fail(f"bootstrap missing on {name} ({missing_names}): run `podiumd-tests bootstrap --env {name}`")
        if missing:
            _auto_bootstrap(podiumd_env, missing)
        for step in wanted:
            (present / step.name).touch()

    return need


@pytest.fixture(scope="session", name="openklant")
def fixture_openklant(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> ApiClient:
    """Open Klant klantinteracties API with the suite's own token (bootstrap step openklant-token)."""
    need_bootstrap("openklant-token")
    return platform.openklant_client(podiumd_env)


@pytest.fixture(scope="session", name="openvtb_verzoeken")
def fixture_openvtb_verzoeken(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> ApiClient:
    """Open VTB's verzoeken API with the suite's own token (bootstrap step openvtb-token)."""
    need_bootstrap("openvtb-token")
    return platform.openvtb_client(podiumd_env, "verzoeken")


@pytest.fixture(scope="session", name="openvtb_taken")
def fixture_openvtb_taken(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> ApiClient:
    """Open VTB's taken API with the suite's own token (bootstrap step openvtb-token)."""
    need_bootstrap("openvtb-token")
    return platform.openvtb_client(podiumd_env, "taken")


@pytest.fixture(scope="session", name="openvtb_berichten")
def fixture_openvtb_berichten(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> ApiClient:
    """Open VTB's berichten API with the suite's own token (bootstrap step openvtb-token)."""
    need_bootstrap("openvtb-token")
    return platform.openvtb_client(podiumd_env, "berichten")


@pytest.fixture(scope="session", name="objecten")
def fixture_objecten(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> ApiClient:
    """Objecten API with the suite's own token (bootstrap step objecten-token)."""
    need_bootstrap("objecten-token")
    return platform.objecten_client(podiumd_env)


@pytest.fixture(scope="session", name="objecttypen")
def fixture_objecttypen(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> ApiClient:
    """Objecttypen API with the suite's own token (bootstrap step objecttypen-token)."""
    need_bootstrap("objecttypen-token")
    return platform.objecttypen_client(podiumd_env)


# The test running now; Open Zaak writes it into its audittrail through X-Audit-Toelichting.
_CURRENT_TEST: ContextVar[str] = ContextVar("current_test", default="")


@pytest.fixture(autouse=True, name="_current_test")
def fixture_current_test(request: pytest.FixtureRequest) -> Iterator[None]:
    """Make the running test's node id available to the API clients."""
    token = _CURRENT_TEST.set(cast("pytest.Item", request.node).nodeid)
    yield
    _CURRENT_TEST.reset(token)


def _zgw_client(  # noqa: PLR0913, PLR0917  # fixture plumbing
    run_tag: str, podiumd_env: Environment, need_bootstrap: Callable[..., None], step: str, client_id: str, key: str
) -> ApiClient:
    need_bootstrap(step)
    return platform.openzaak_client(podiumd_env, client_id, key, run_tag, _CURRENT_TEST.get)


@pytest.fixture(scope="session", name="openzaak")
def fixture_openzaak(run_tag: str, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> ApiClient:
    """Open Zaak's ZGW APIs as the suite's own client, with a fresh token per request."""
    return _zgw_client(
        run_tag, podiumd_env, need_bootstrap, "openzaak-client", names.ZGW_CLIENT_ID, names.ZGW_STORE_KEY
    )


@pytest.fixture(scope="session", name="zgw_secret")
def fixture_zgw_secret(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> str:
    """Return the secret of the suite's own ZGW client, for tests that build their own tokens."""
    need_bootstrap("openzaak-client")
    return podiumd_env.credentials.get(names.ZGW_STORE_KEY)


@pytest.fixture(scope="session", name="openzaak_openbaar")
def fixture_openzaak_openbaar(run_tag: str, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> ApiClient:
    """Open Zaak as a client that sees vertrouwelijkheid openbaar at most and cannot delete."""
    return _zgw_client(
        run_tag,
        podiumd_env,
        need_bootstrap,
        "openzaak-client-openbaar",
        names.ZGW_OPENBAAR_CLIENT_ID,
        names.ZGW_OPENBAAR_STORE_KEY,
    )


@pytest.fixture(scope="session", name="openzaak_gesloten")
def fixture_openzaak_gesloten(run_tag: str, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> ApiClient:
    """Open Zaak as a client without zaken.geforceerd-bijwerken, zaken.heropenen and documenten.geforceerd-unlock."""
    return _zgw_client(
        run_tag,
        podiumd_env,
        need_bootstrap,
        "openzaak-client-gesloten",
        names.ZGW_GESLOTEN_CLIENT_ID,
        names.ZGW_GESLOTEN_STORE_KEY,
    )


@pytest.fixture(scope="session", name="openzaak_noauth")
def fixture_openzaak_noauth(run_tag: str, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> ApiClient:
    """Open Zaak as a known client without any autorisatie."""
    return _zgw_client(
        run_tag,
        podiumd_env,
        need_bootstrap,
        "openzaak-client-noauth",
        names.ZGW_NOAUTH_CLIENT_ID,
        names.ZGW_NOAUTH_STORE_KEY,
    )


@pytest.fixture(scope="session", name="openzaak_productaanvraag")
def fixture_openzaak_productaanvraag(  # noqa: WPS118  # fixture_<name> of fixture openzaak_productaanvraag
    run_tag: str, podiumd_env: Environment, need_bootstrap: Callable[..., None]
) -> ApiClient:
    """Open Zaak as the client that may only read and delete zaken of the productaanvraag zaaktype."""
    return _zgw_client(
        run_tag,
        podiumd_env,
        need_bootstrap,
        "openzaak-client-productaanvraag",
        names.ZGW_PRODUCTAANVRAAG_CLIENT_ID,
        names.ZGW_PRODUCTAANVRAAG_STORE_KEY,
    )


@pytest.fixture(scope="session", name="opennotificaties")
def fixture_opennotificaties(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> ApiClient:
    """Open Notificaties as the suite's own client ptest-bootstrap-nrc."""
    need_bootstrap("opennotificaties-client")
    return platform.opennotificaties_client(podiumd_env)


@pytest.fixture(scope="session", name="test_zaaktype")
def fixture_test_zaaktype(openzaak: ApiClient, need_bootstrap: Callable[..., None]) -> JsonObject:
    """Return the published test zaaktype in the test catalogus (bootstrap step openzaak-zaaktype)."""
    need_bootstrap("openzaak-zaaktype")
    return published_zaaktype(openzaak, names.TEST_ZAAKTYPE, "openzaak-zaaktype")


@pytest.fixture(scope="session", name="archief_parts")
def fixture_archief_parts(openzaak: ApiClient, need_bootstrap: Callable[..., None]) -> ZaaktypeParts:
    """Return the types of the archief zaaktype, a second zaaktype in the test catalogus."""
    need_bootstrap("openzaak-zaaktype-archief")
    return zaaktype_parts(openzaak, published_zaaktype(openzaak, names.ARCHIEF_ZAAKTYPE, "openzaak-zaaktype-archief"))


@pytest.fixture(scope="session", name="parts")
def fixture_parts(openzaak: ApiClient, test_zaaktype: JsonObject) -> ZaaktypeParts:
    """Return the statustypen, roltypen and other types of the test zaaktype."""
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
    """Return the environment's Mailpit API."""
    return platform.mailpit_client(podiumd_env)


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
    """Make callback paths of this test's own on the mock server (infra/mock-server); takes fail_first."""
    need_bootstrap("infra-mock-server")
    return functools.partial(Callback.new, podiumd_env, run_tag)


@pytest.fixture(name="callback")
def fixture_callback(new_callback: Callable[..., Callback]) -> Callback:
    """Return a callback path of this test's own on the mock server."""
    return new_callback()


@pytest.fixture(scope="session", name="productaanvraagtype")
def fixture_productaanvraagtype(podiumd_env: Environment) -> str:
    """Return the productaanvraagtype ZAC starts zaken for (profile setting productaanvraag_type); skips without it."""
    found = podiumd_env.profile.settings.get("productaanvraag_type")
    if not found:
        pytest.skip(f"profile {podiumd_env.profile.name} has no settings.productaanvraag_type")
    return found


@pytest.fixture(scope="session", name="productaanvraag_objecttype")
def fixture_productaanvraag_objecttype(  # noqa: WPS118  # fixture_<name> of fixture productaanvraag_objecttype
    podiumd_env: Environment,
) -> str:
    """Return the productaanvraag objecttype's URL as Objecten knows it."""
    return objecttype_url(podiumd_env, names.PRODUCTAANVRAAG_OBJECTTYPE)


@pytest.fixture(name="ontvangstbevestiging")
def fixture_ontvangstbevestiging(
    zac: requests.Session, podiumd_env: Environment, need_bootstrap: Callable[..., None]
) -> None:
    """Skips unless ZAC mails an ontvangstbevestiging for productaanvragen (of setting productaanvraag_zaaktype)."""
    need_bootstrap("zac-email-confirmation")
    zaaktype = str(podiumd_env.profile.settings.get("productaanvraag_zaaktype"))
    if not is_confirmation_on(zac, podiumd_env.profile.urls["zac"], zaaktype):
        pytest.skip(
            f"ZAC sends no ontvangstbevestiging for {zaaktype}: allow it with profile setting zac_email_confirmation"
        )


@pytest.fixture(name="kiss_session")
def fixture_kiss_session(
    podiumd_env: Environment, urls: dict[str, str], need_bootstrap: Callable[..., None]
) -> Callable[[KeycloakUser], requests.Session]:
    """Return a KISS session of a test user, logged in through Keycloak without a browser."""

    def login(user: KeycloakUser) -> requests.Session:
        need_bootstrap(user.name)
        return challenge_session(podiumd_env, urls["kiss"], user.username, podiumd_env.credentials.get(user.store_key))

    return login


@pytest.fixture(name="zac")
def fixture_zac(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> requests.Session:
    """Return the test admin's session on ZAC's REST API."""
    need_bootstrap(steps.ADMIN.name)
    return zac_as_admin(podiumd_env)


@pytest.fixture(name="zac_as")
def fixture_zac_as(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> Callable[[str], requests.Session]:
    """Return a login to ZAC as the test user of one application role; skips below ZAC 5.9.1."""
    skip_older_than(podiumd_env, "zac", (5, 9, 1), "the role tests follow its policies")
    need_bootstrap("zac-bpmn-process")

    def login(role: str) -> requests.Session:
        user = steps.ZAC_ROLE_USERS[role]
        need_bootstrap(user.name)
        return zac_session(podiumd_env, user.username, podiumd_env.credentials.get(user.store_key))

    return login


@pytest.fixture(name="zac_group")
def fixture_zac_group(zac: requests.Session, urls: dict[str, str]) -> str:
    """Return a group of the test admin, to assign zaken and taken to together with the admin."""
    return user_groups(zac, urls["zac"])[0]


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
    """Start a zaak in ZAC with a run-tagged omschrijving; cleanup ends its BPMN process and deletes it."""

    def start(**fields: object) -> JsonObject:
        zaak = create_zaak(zac, urls["zac"], zac_parameters, omschrijving=registry.tagged("zac-zaak"), **fields)
        clean_up_zaak(zac, urls["zac"], openzaak_productaanvraag, registry, zaak)
        return zaak

    return start


@pytest.fixture(name="bpmn_zaaktype")
def fixture_bpmn_zaaktype(openzaak: ApiClient, need_bootstrap: Callable[..., None]) -> JsonObject:
    """Return the BPMN test zaaktype, which ZAC handles with podiumd-tests' BPMN process."""
    need_bootstrap("openzaak-zaaktype-bpmn", "zac-bpmn-process")
    return published_zaaktype(openzaak, names.BPMN_ZAAKTYPE, "openzaak-zaaktype-bpmn")


@pytest.fixture(name="bpmn_parameters")
def fixture_bpmn_parameters(bpmn_zaaktype: JsonObject, zac_group: str) -> JsonObject:
    """Return what create_zaak reads of zaakafhandelparameters, for the BPMN test zaaktype in the test admin's group."""
    zaaktype = {"uuid": uuid_of(bpmn_zaaktype["url"]), "omschrijving": bpmn_zaaktype["omschrijving"]}
    return {"zaaktype": zaaktype, "defaultGroepId": zac_group}


@pytest.fixture(name="bpmn_zaak")
def fixture_bpmn_zaak(
    zac: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    bpmn_parameters: JsonObject,
    registry: ResourceRegistry,
) -> JsonObject:
    """Start a zaak of the BPMN test zaaktype in ZAC; cleanup ends its process and deletes it and its documents."""
    zaak = create_zaak(zac, urls["zac"], bpmn_parameters, omschrijving=registry.tagged("bpmn"))
    clean_up_zaak(zac, urls["zac"], openzaak, registry, zaak)
    return zaak


@pytest.hookimpl(tryfirst=True)  # before xdist reads the groups
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Put the destructive tests in one xdist group; record each test's sources and scenario as junit properties.

    Tests using several_replicas are destructive where the fixture switches pods (tier chaos), so the
    switch runs once, apart from parallel tests. A test without a valid source marker, or with a malformed
    scenario, stops the run.
    """
    problems = [problem for item in items for problem in (*source_problems(item), *scenarios.scenario_problems(item))]
    if problems:
        raise pytest.UsageError("\n".join(problems))
    switching = any(
        "several_replicas" in getattr(test, "fixturenames", ()) for test in items
    ) and replicas.can_switch_replicas(_environment(config).profile)
    for item in items:
        if switching and "several_replicas" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.destructive)
        if item.get_closest_marker("destructive"):
            item.add_marker(pytest.mark.xdist_group("destructive"))
        item.user_properties += [("source", source) for source in sources(item)]
        text = scenarios.scenario(item)
        if text:
            item.user_properties.append(("scenario", text))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Record a non-strict xpass and its reason as junit property "xpass", and show the scenario in report.html."""
    report = yield
    if call.when == "call" and report.passed and hasattr(report, "wasxfail"):
        # junit writes the properties of the teardown report, which copies the item's.
        item.user_properties.append(("xpass", str(report.wasxfail)))
    text = scenarios.scenario(item) if call.when == "call" else ""
    if text:
        # pytest-html shows a report's extras (its extras.html() shape) in the row's detail.
        extra = {
            "name": None,
            "format_type": "html",
            "content": f"<pre>{escape(text)}</pre>",
            "mime_type": None,
            "extension": None,
        }
        vars(report)["extras"] = [*vars(report).get("extras", []), extra]
    return report


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip tests whose @pytest.mark.requires(...) capabilities are absent.

    A hook rather than an autouse fixture: it runs before any fixture, also
    before module- or session-scoped ones that would need the capability.
    """
    needed = [
        str(capability)
        for marker in item.iter_markers("requires")
        for capability in cast("tuple[object, ...]", marker.args)
    ]
    if needed:
        reason = _environment(item.config).capabilities.skip_reason(*needed)
        if reason:
            pytest.skip(reason)


def public_url(podiumd_env: Environment, urls: dict[str, str], component: str) -> str:
    """Return the component's URL; skips when the profile reaches it in the cluster (no public host).

    The profile URL decides: `urls` holds the port-forwarded 127.0.0.1 URL of an in-cluster component.
    """
    if cluster_service(podiumd_env.profile.urls[component]):
        pytest.skip(f"{component} has no public host in this profile")
    return urls[component]


def requiring(
    component: str, *values: object, test_id: str | None = None, marks: Sequence[pytest.MarkDecorator] = ()
) -> ParameterSet:
    """Return a pytest.param with these values that skips unless the environment has the component; marks add to that.

    For tests parametrized per component, e.g. [requiring(c, c) for c in COMPONENTS].
    """
    all_marks = [pytest.mark.requires(component), *marks]
    return pytest.param(*values, id=test_id or component, marks=all_marks)
