"""Continuity under load: a component breaks while the platform is busy, comes back, and no work is lost.

Each test runs a modest load of the suite's own calls on a few threads, breaks one component for a bounded
time, restores it and checks that every piece of work the load started is finished and nothing else restarted.
"""

from __future__ import annotations

import time

from contextlib import suppress
from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests import openformulieren as forms
from podiumd_tests import workloads
from podiumd_tests.auth import keycloak_admin
from podiumd_tests.auth.keycloak import PasswordLogin
from podiumd_tests.auth.keycloak import form_login
from podiumd_tests.auth.keycloak import password_grant
from podiumd_tests.bootstrap.names import BPMN_ZAAKTYPE
from podiumd_tests.bootstrap.names import TEST_CATALOGUS_RSIN
from podiumd_tests.bootstrap.names import TEST_FORM
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.bootstrap.steps import NAW_DATA
from podiumd_tests.chaos_load import CALM
from podiumd_tests.chaos_load import DELIVERY_TIMEOUT
from podiumd_tests.chaos_load import failures
from podiumd_tests.chaos_load import load_report
from podiumd_tests.chaos_load import recovery_seconds
from podiumd_tests.chaos_load import slowdown
from podiumd_tests.chaos_load import watched_load
from podiumd_tests.clients.api import per_thread
from podiumd_tests.components import COMPONENTS
from podiumd_tests.defects import DefectSymptomError
from podiumd_tests.defects import symptom
from podiumd_tests.oidc import LOGIN_PATHS
from podiumd_tests.perf.availability_report import problems
from podiumd_tests.seed.opennotificaties import delivery_attempts
from podiumd_tests.seed.opennotificaties import make_abonnement
from podiumd_tests.seed.openzaak import published_zaaktype
from podiumd_tests.seed.openzaak import zaak_maker
from podiumd_tests.seed.registry import ResourceRegistry
from podiumd_tests.seed.zac_zaaktype import zac_as_admin
from podiumd_tests.wait import WaitTimeoutError
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import is_zaak_listed
from podiumd_tests.zac import logged_in_user

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.chaos_load import Attempt
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.mock_server import Callback

pytestmark = [
    pytest.mark.integration,
    pytest.mark.destructive,
    pytest.mark.slow,
    pytest.mark.requires("cluster"),
]

# Seconds a component stays broken.
OUTAGE = 60
# Seconds of load while a subscriber refuses: Open Notificaties' default retries of one notificatie span about 160 s.
REFUSING = 180
# Only this test's zaken carry it, so the refusing subscriber gets no other test's notificaties.
REFUSED_VERTROUWELIJKHEID = "zaakvertrouwelijk"
# Open Formulieren registers each submission in a Celery task once its worker is back.
REGISTRATION_TIMEOUT = 300
# Open Formulieren throttles _complete to 10 per minute per client address.
COMPLETE_TIMEOUT = 120
# A deleted Keycloak pod is replaced and serves logins again.
KEYCLOAK_RECOVERY = 300
# A deleted ZAC pod is replaced and ready: its readiness probe starts after 60 s and allows 20 x 10 s.
ZAC_RECOVERY = 600
# Seconds past an access token's expiry by which a session has refreshed it.
REFRESH_MARGIN = 60


@pytest.mark.requires("openzaak", "opennotificaties")
@pytest.mark.source(
    "upstream open-zaak/open-zaak docs/development/performance/notifications.rst",
    "With Open Notificaties down for up to 60 s under write load, the default autoretry loses no notificatie.",
)
@pytest.mark.parametrize("stopped", ["opennotificaties", "openzaak-worker"])
@pytest.mark.scenario("""
    Given a subscriber on kanaal zaken in Open Notificaties
    And zaken are created in Open Zaak without pause
    When Open Notificaties, or the worker that sends Open Zaak's notifications, is stopped for a minute
    Then Open Zaak created every zaak
    And the subscriber gets the notification of every zaak once it is started again
    And no other component restarted
""")
def test_no_notificatie_is_lost_while_the_notifier_is_down(  # fixtures
    podiumd_env: Environment,
    urls: dict[str, str],
    http: requests.Session,
    run_tag: str,
    opennotificaties: ApiClient,
    test_zaaktype: JsonObject,
    registry: ResourceRegistry,
    new_callback: Callable[..., Callback],
    record_property: Callable[[str, object], None],
    stopped: str,
) -> None:
    """Every zaak created while Open Notificaties or Open Zaak's worker is down reaches the subscriber once it is back."""
    if stopped == "opennotificaties":
        deployment = podiumd_env.deployment_for(stopped)
        outage = workloads.component_down(podiumd_env, http, stopped)
    else:
        deployment = workloads.worker_deployment(podiumd_env, "openzaak")
        if deployment is None:
            pytest.skip(f"no worker Deployment of openzaak on {podiumd_env.profile.name}")
        outage = workloads.scaled(podiumd_env.kube, f"deployment/{deployment}", 0)
    callback = new_callback()
    make_abonnement(opennotificaties, registry, callback.url, "zaken", {"bronorganisatie": TEST_CATALOGUS_RSIN})
    before = workloads.cluster_state(podiumd_env)
    start = time.time()
    calls = {"oz_zaak_create": zaak_maker(podiumd_env, run_tag, registry, str(test_zaaktype["url"]))}
    besides = {deployment}
    with watched_load(podiumd_env, urls, ["openzaak"], calls, workers=2, pause=1, besides=besides) as (load, watch):
        load.run_for(CALM)
        with outage:
            down = time.time()
            load.run_for(OUTAGE)
        back = time.time()
        load.run_for(CALM)
    record_property("report", load_report(load, watch, start))
    assert [*failures(load.attempts, start), *problems(watch)] == []
    zaken = load.created()
    lost = callback.missing(zaken, DELIVERY_TIMEOUT)
    record_property("outage_seconds", round(back - down))
    record_property("delivered_seconds_after_restart", round(time.time() - back))
    assert lost == [], f"{len(lost)} of {len(zaken)} notificaties lost"
    assert workloads.disruptions(before, workloads.cluster_state(podiumd_env), {deployment}) == []


@pytest.mark.requires("openzaak", "opennotificaties")
@pytest.mark.source(
    "external maykinmedia/open-object#534",
    "A subscriber that answered 403 drove 10k deliveries a minute and 100 % database use; every component degraded.",
)
@pytest.mark.scenario("""
    Given a subscriber on kanaal zaken in Open Notificaties
    And zaken are created in Open Zaak without pause
    When a second subscriber refuses every notification for three minutes
    Then Open Zaak creates zaken as fast as before and no component restarts
    And Open Notificaties stops sending each refused notification after its retries
    And the first subscriber gets the notification of every zaak
""")
def test_a_refusing_subscriber_does_not_slow_down_open_zaak(  # fixtures
    podiumd_env: Environment,
    urls: dict[str, str],
    run_tag: str,
    opennotificaties: ApiClient,
    test_zaaktype: JsonObject,
    registry: ResourceRegistry,
    new_callback: Callable[..., Callback],
    record_property: Callable[[str, object], None],
) -> None:
    """Under write load, a subscriber that answers 403 gets each notificatie once plus Open Notificaties' retries.

    Open Zaak's p95 of a zaak create stays within perf.yaml's slowdown limit and the other subscriber gets every one.
    """
    healthy, refusing = new_callback(), new_callback(answer="refuse")
    make_abonnement(opennotificaties, registry, healthy.url, "zaken", {"bronorganisatie": TEST_CATALOGUS_RSIN})
    deliveries = delivery_attempts(podiumd_env)
    # Removed before the refusing abonnement: their delete notificaties would schedule retries that block its removal.
    load_registry = ResourceRegistry(run_tag)
    registry.add("zaken of the load", load_registry.cleanup)
    vertrouwelijk = {"vertrouwelijkheidaanduiding": REFUSED_VERTROUWELIJKHEID}
    before = workloads.cluster_state(podiumd_env)
    start = time.time()
    zaaktype = str(test_zaaktype["url"])
    calls = {"oz_zaak_create": zaak_maker(podiumd_env, run_tag, load_registry, zaaktype, **vertrouwelijk)}
    served = ["openzaak", "opennotificaties"]
    with watched_load(podiumd_env, urls, served, calls, workers=2, pause=1) as (load, watch):
        load.run_for(CALM)
        filters = {"bronorganisatie": TEST_CATALOGUS_RSIN, **vertrouwelijk}
        make_abonnement(opennotificaties, registry, refusing.url, "zaken", filters)
        refused_since = time.time()
        load.run_for(REFUSING)
    ended = time.time()
    zaken = load.created()
    later = load.created(refused_since)

    def is_settled() -> bool:
        refused = refusing.notified("zaken", "zaak", "create")
        return not healthy.missing(zaken) and all(refused[zaak] >= deliveries for zaak in later)

    with suppress(WaitTimeoutError):
        wait_until(is_settled, timeout=DELIVERY_TIMEOUT, interval=10, description="every delivery and retry")
    refused = refusing.notified("zaken", "zaak", "create")
    calm, refusal, limit = slowdown(load.attempts, refused_since, "oz_zaak_create")
    record_property("report", load_report(load, watch, start))
    measured = {
        "p95_ms": {"before": round(calm), "while_refusing": round(refusal), "limit": round(limit)},
        "refused": {"notificaties": len(later), "deliveries": sum(refused[zaak] for zaak in zaken)},
        "settled_seconds_after_load": round(time.time() - ended),
    }
    record_property("measured", measured)
    assert [*failures(load.attempts, start), *problems(watch)] == []
    assert workloads.disruptions(before, workloads.cluster_state(podiumd_env), set()) == []
    assert refusal <= limit, f"p95 while refusing {refusal:.0f} ms > {limit:.0f} ms (before {calm:.0f})"
    lost = healthy.missing(zaken)
    assert lost == [], f"{len(lost)} of {len(zaken)} notificaties lost"
    unbounded = {zaak: refused[zaak] for zaak in zaken if refused[zaak] > deliveries}
    assert unbounded == {}, f"more than {deliveries} deliveries of a refused notificatie"
    unretried = {zaak: refused[zaak] for zaak in later if refused[zaak] < deliveries}
    assert unretried == {}, f"fewer than {deliveries} deliveries of a refused notificatie in {DELIVERY_TIMEOUT} s"


@pytest.mark.requires("openzaak", "opennotificaties", "zac")
@pytest.mark.source(
    "podiumd-tests",
    "ZAC learns of a new zaak only from Open Notificaties; no source test restarts ZAC while zaken arrive.",
)
@pytest.mark.scenario("""
    Given zaken are created in Open Zaak without pause
    When ZAC's pod is restarted
    Then ZAC's search finds every zaak once ZAC is back
    And no other component restarted
""")
def test_zac_finds_the_zaken_made_while_it_restarts(
    podiumd_env: Environment,
    urls: dict[str, str],
    run_tag: str,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
    record_property: Callable[[str, object], None],
) -> None:
    """ZAC's search finds every zaak Open Zaak created while ZAC's pod was replaced."""
    need_bootstrap(ADMIN.name, "openzaak-zaaktype-bpmn", "zac-bpmn-process")
    deployment = podiumd_env.deployment_for("zac")
    pods = [pod for pod in podiumd_env.items("pods") if workloads.pod_workload(pod) == deployment]
    assert pods, f"no pod of {deployment}"
    zaaktype = str(published_zaaktype(openzaak, BPMN_ZAAKTYPE, "openzaak-zaaktype-bpmn")["url"])
    before = workloads.cluster_state(podiumd_env)
    start = time.time()
    calls = {"oz_zaak_create": zaak_maker(podiumd_env, run_tag, registry, zaaktype)}
    with watched_load(podiumd_env, urls, ["openzaak"], calls, workers=1, pause=2) as (load, watch):
        load.run_for(CALM)
        workloads.replace_pod(podiumd_env, pods[0], ZAC_RECOVERY)
        back = time.time()
        load.run_for(CALM)
    record_property("report", load_report(load, watch, start))
    record_property("zac_back_seconds", round(back - start - CALM))
    assert [*failures(load.attempts, start), *problems(watch)] == []
    zac, zac_url = zac_as_admin(podiumd_env), urls["zac"]
    zaken = [cast("JsonObject", attempt.result) for attempt in load.attempts if attempt.error is None]

    def unlisted() -> list[str]:
        return [str(zaak["identificatie"]) for zaak in zaken if not is_zaak_listed(zac, zac_url, zaak)]

    with suppress(WaitTimeoutError):
        wait_until(lambda: not unlisted(), timeout=DELIVERY_TIMEOUT, interval=10, description="every zaak in ZAC")
    missing = unlisted()
    assert missing == [], f"ZAC's search misses {len(missing)} of {len(zaken)} zaken: {missing}"
    assert workloads.disruptions(before, workloads.cluster_state(podiumd_env), {deployment}) == []


type Sent = tuple[requests.Session, str, str]


def sender(env: Environment, registry: ResourceRegistry) -> Callable[[], Sent]:
    """Return a call that submits the test form anonymously: its session, submission uuid and status URL."""
    base_url = env.profile.urls["openformulieren"]

    def send() -> Sent:
        session = env.session()
        submission, headers = forms.start_submission(session, base_url, TEST_FORM)
        forms.forget_submission(env, registry, str(submission["id"]))
        data = {"klacht_omschrijving": registry.tagged("klacht"), **NAW_DATA}
        status_url = forms.send_submission(session, submission, headers, data, timeout=COMPLETE_TIMEOUT)
        return session, str(submission["id"]), status_url

    return send


def unregistered(
    env: Environment, openzaak: ApiClient, registry: ResourceRegistry, attempts: list[Attempt], since: float
) -> list[str]:
    """Return one line per sent submission that did not become a zaak within REGISTRATION_TIMEOUT."""
    deadline = time.monotonic() + REGISTRATION_TIMEOUT

    def register(sent: Sent) -> None:
        session, submission, status_url = sent
        timeout = max(deadline - time.monotonic(), CALM)
        status = forms.submission_result(session, status_url, submission, timeout=timeout)
        forms.wait_for_registration(env, submission, timeout=timeout)
        forms.registered_zaak(env, openzaak, registry, status)

    lost: list[str] = []
    for attempt in attempts:
        try:
            register(cast("Sent", attempt.result))
        except AssertionError as exc:
            lost.append(f"sent at +{attempt.start - since:.0f}s: {exc}")
            forget_preregistered_zaak(env, openzaak, registry, cast("Sent", attempt.result)[1])
    return lost


def forget_preregistered_zaak(
    env: Environment, openzaak: ApiClient, registry: ResourceRegistry, submission: str
) -> None:
    """Cleanup deletes the zaak an unregistered submission's pre-registration made, if there is one."""
    reference = forms.registration_state(env, submission)["reference"]
    if not reference:  # an empty identificatie filter would match every zaak
        return
    with suppress(AssertionError):  # no zaak: the pre-registration did not run
        forms.registered_zaak(env, openzaak, registry, {"submission": submission, "publicReference": reference})


@pytest.mark.requires("openformulieren", "openzaak")
@pytest.mark.source(
    "upstream open-formulieren/open-forms #2198",
    "Under load the Celery worker stopped; after its restart queued registrations stayed pending.",
)
@pytest.mark.scenario("""
    Given anonymous inwoners submit the test form one after another
    When the worker of Open Formulieren is stopped for a minute and started again
    Then Open Formulieren accepted every submission
    And every submission is registered as a zaak in Open Zaak
    And no other component restarted
""")
def test_no_submission_is_lost_while_the_open_formulieren_worker_is_down(
    podiumd_env: Environment,
    urls: dict[str, str],
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
    record_property: Callable[[str, object], None],
) -> None:
    """Every form submitted while Open Formulieren's worker is down is registered as a zaak once it is back."""
    need_bootstrap("openformulieren-form", "openformulieren-zgw-group", "openzaak-of-autorisatie")
    worker = workloads.worker_deployment(podiumd_env, "openformulieren")
    if worker is None:
        pytest.skip(f"no worker Deployment of openformulieren on {podiumd_env.profile.name}")
    before = workloads.cluster_state(podiumd_env)
    start = time.time()
    calls = {"of_submit": sender(podiumd_env, registry)}
    with watched_load(podiumd_env, urls, ["openzaak"], calls, workers=2, pause=2) as (load, watch):
        load.run_for(CALM)
        with workloads.scaled(podiumd_env.kube, f"deployment/{worker}", 0):
            load.run_for(OUTAGE)
        back = time.time()
        load.run_for(CALM)
    record_property("report", load_report(load, watch, start))
    assert [*failures(load.attempts, start), *problems(watch)] == []
    lost = unregistered(podiumd_env, openzaak, registry, load.attempts, start)
    record_property("registered_seconds_after_restart", round(time.time() - back))
    assert lost == [], f"{len(lost)} of {len(load.attempts)} submissions not registered"
    assert workloads.disruptions(before, workloads.cluster_state(podiumd_env), {worker}) == []


@pytest.mark.requires("openformulieren", "openzaak")
@pytest.mark.source(
    "podiumd-tests",
    "The apps share one Postgres server; no source test restarts it while forms are submitted.",
)
@pytest.mark.xfail(
    strict=True,
    raises=DefectSymptomError,
    reason="[open-formulieren-8] Open Formulieren 4.0.7 leaves a submission whose processing task failed on the"
    " unreachable database pending without needs_on_completion_retry, so it is never registered; not yet reported upstream",
)
@pytest.mark.scenario("""
    Given anonymous inwoners submit the test form one after another
    When the database server is restarted
    Then every submission Open Formulieren accepted is registered as a zaak in Open Zaak
""")
def test_no_accepted_submission_is_lost_when_postgres_restarts(
    podiumd_env: Environment,
    urls: dict[str, str],
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
    record_property: Callable[[str, object], None],
) -> None:
    """Every form Open Formulieren accepted around a Postgres restart is registered as a zaak."""
    database = workloads.database_pod(podiumd_env)
    if database is None:
        pytest.skip(f"Open Zaak's database runs outside the cluster on {podiumd_env.profile.name}")
    need_bootstrap("openformulieren-form", "openformulieren-zgw-group", "openzaak-of-autorisatie")
    start = time.time()
    calls = {"of_submit": sender(podiumd_env, registry)}
    with watched_load(podiumd_env, urls, ["openformulieren"], calls, workers=2, pause=2) as (load, watch):
        load.run_for(CALM)
        workloads.replace_pod(podiumd_env, database, OUTAGE * 5)
        load.run_for(OUTAGE)
    record_property("report", load_report(load, watch, start))
    accepted = [attempt for attempt in load.attempts if attempt.error is None]
    lost = unregistered(podiumd_env, openzaak, registry, accepted, start)
    with symptom():
        assert lost == [], f"{len(lost)} of {len(accepted)} accepted submissions not registered"


def login_calls(env: Environment) -> dict[str, Callable[[], object]]:
    """Return a token request of Keycloak's admin and a KISS login of the KCC medewerker."""
    urls, credentials = env.profile.urls, env.credentials
    admin = PasswordLogin(
        "admin-cli", credentials.get("keycloak_admin_username"), credentials.get("keycloak_admin_password")
    )
    session = per_thread(env.session)
    password = credentials.get(KCC.store_key)
    return {
        "kc_token": lambda: password_grant(session(), urls["keycloak"], "master", admin),
        "kc_login_kiss": lambda: form_login(env.session(), urls["kiss"] + LOGIN_PATHS["kiss"], KCC.username, password),
    }


@pytest.mark.requires("keycloak", "kiss")
@pytest.mark.source(
    "upstream keycloak/keycloak-benchmark benchmark/src/main/content/bin/kc-chaos.sh",
    "Deletes a Keycloak pod under load and records how long logins take to recover.",
)
@pytest.mark.scenario("""
    Given medewerkers log in to KISS and a client asks Keycloak for tokens without pause
    When a Keycloak instance is stopped
    Then logins and tokens work again once Keycloak has replaced it
    And no other component restarted
""")
def test_logins_recover_after_a_keycloak_pod_is_deleted(
    podiumd_env: Environment,
    urls: dict[str, str],
    need_bootstrap: Callable[..., None],
    record_property: Callable[[str, object], None],
) -> None:
    """Logins and token requests recover after a Keycloak pod is deleted; the recovery time is recorded.

    With one Keycloak instance there is no HA: the test measures the outage and asserts the recovery only.
    """
    need_bootstrap(KCC.name)
    calls = login_calls(podiumd_env)
    names = COMPONENTS["keycloak"].deployment_prefixes
    pods = [pod for pod in podiumd_env.items("pods") if workloads.pod_workload(pod) in names]
    assert pods, "no Keycloak pod"
    workload = str(workloads.pod_workload(pods[0]))
    record_property("keycloak_pods", len(pods))
    before = workloads.cluster_state(podiumd_env)
    with watched_load(podiumd_env, urls, ["kiss"], calls, workers=2, pause=1) as (load, watch):
        load.run_for(CALM)
        deleted = time.time()
        workloads.replace_pod(podiumd_env, pods[0], KEYCLOAK_RECOVERY)
        load.run_for(CALM)
    record_property("report", load_report(load, watch, deleted))
    recovered = {
        name: recovery_seconds([attempt for attempt in load.attempts if attempt.name == name], deleted)
        for name in calls
    }
    record_property("recovery_seconds", recovered)
    assert None not in recovered.values(), f"not recovered: {recovered}"
    assert problems(watch) == []
    assert workloads.disruptions(before, workloads.cluster_state(podiumd_env), {workload}) == []


@pytest.mark.requires("keycloak", "zac")
@pytest.mark.source(
    "podiumd-tests",
    "ZAC refreshes its users' tokens at Keycloak; no source test restarts Keycloak while a medewerker is logged in.",
)
@pytest.mark.scenario("""
    Given the test admin is logged in to ZAC
    When a Keycloak instance is stopped and replaced
    Then the test admin keeps working in ZAC without logging in again
    And still after ZAC had to refresh the admin's access token
""")
def test_zac_session_survives_a_keycloak_restart(
    podiumd_env: Environment,
    urls: dict[str, str],
    need_bootstrap: Callable[..., None],
    record_property: Callable[[str, object], None],
) -> None:
    """A ZAC session logged in before a Keycloak pod is deleted keeps working past its access token's lifespan."""
    need_bootstrap(ADMIN.name)
    lifespan = int(str(keycloak_admin.for_environment(podiumd_env).representation()["accessTokenLifespan"]))
    names = COMPONENTS["keycloak"].deployment_prefixes
    pods = [pod for pod in podiumd_env.items("pods") if workloads.pod_workload(pod) in names]
    assert pods, "no Keycloak pod"
    zac, zac_url = zac_as_admin(podiumd_env), urls["zac"]
    logged_in = time.time()
    calls = {"zac_logged_in_user": lambda: logged_in_user(zac, zac_url)}
    with watched_load(podiumd_env, urls, ["zac"], calls, workers=1, pause=5) as (load, watch):
        workloads.replace_pod(podiumd_env, pods[0], KEYCLOAK_RECOVERY)
        # Past the access token's expiry, so ZAC refreshes it at the new Keycloak instance.
        load.run_for(max(logged_in + lifespan + REFRESH_MARGIN - time.time(), CALM))
    record_property("report", load_report(load, watch, logged_in))
    record_property("access_token_lifespan", lifespan)
    assert failures(load.attempts, logged_in) == [], "the ZAC session failed around the Keycloak restart"
