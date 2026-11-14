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

from podiumd_tests.auth.keycloak import PasswordLogin
from podiumd_tests.auth.keycloak import form_login
from podiumd_tests.auth.keycloak import password_grant
from podiumd_tests.bootstrap.names import TEST_CATALOGUS_RSIN
from podiumd_tests.bootstrap.names import TEST_FORM
from podiumd_tests.bootstrap.names import ZGW_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_STORE_KEY
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.bootstrap.steps import NAW_DATA
from podiumd_tests.chaos_load import failures
from podiumd_tests.chaos_load import load_report
from podiumd_tests.chaos_load import recovery_seconds
from podiumd_tests.chaos_load import watched_load
from podiumd_tests.clients.api import per_thread
from podiumd_tests.clients.platform import openzaak_client
from podiumd_tests.components import COMPONENTS
from podiumd_tests.mock_server import notification
from podiumd_tests.oidc import LOGIN_PATHS
from podiumd_tests.openformulieren import forget_submission
from podiumd_tests.openformulieren import registered_zaak
from podiumd_tests.openformulieren import send_submission
from podiumd_tests.openformulieren import start_submission
from podiumd_tests.openformulieren import submission_result
from podiumd_tests.openformulieren import wait_for_registration
from podiumd_tests.perf.availability_report import problems
from podiumd_tests.seed.opennotificaties import make_abonnement
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.wait import WaitTimeoutError
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import cluster_state
from podiumd_tests.workloads import component_down
from podiumd_tests.workloads import disruptions
from podiumd_tests.workloads import pod_workload
from podiumd_tests.workloads import replace_pod
from podiumd_tests.workloads import scaled
from podiumd_tests.workloads import worker_deployment

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.chaos_load import Attempt
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.mock_server import Callback
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.destructive,
    pytest.mark.slow,
    pytest.mark.requires("cluster"),
]

# Seconds a component stays broken, and seconds of load before and after.
OUTAGE = 60
CALM = 15
# Open Zaak retries a failed notificatie 5 times, at most 48 s apart (NotificationsConfig defaults).
DELIVERY_TIMEOUT = 300
# Open Formulieren registers each submission in a Celery task once its worker is back.
REGISTRATION_TIMEOUT = 300
# Open Formulieren throttles _complete to 10 per minute per client address.
COMPLETE_TIMEOUT = 120
# A deleted Keycloak pod is replaced and serves logins again.
KEYCLOAK_RECOVERY = 300


@pytest.mark.requires("openzaak", "opennotificaties")
@pytest.mark.source(
    "upstream open-zaak/open-zaak docs/development/performance/notifications.rst",
    "With Open Notificaties down for up to 60 s under write load, the default autoretry loses no notificatie.",
)
@pytest.mark.scenario("""
    Given a subscriber on kanaal zaken in Open Notificaties
    And zaken are created in Open Zaak without pause
    When Open Notificaties is stopped for a minute and started again
    Then Open Zaak created every zaak
    And the subscriber gets the notification of every zaak
    And no other component restarted
""")
def test_no_notificatie_is_lost_while_open_notificaties_is_down(  # fixtures
    podiumd_env: Environment,
    urls: dict[str, str],
    http: requests.Session,
    run_tag: str,
    opennotificaties: ApiClient,
    test_zaaktype: JsonObject,
    registry: ResourceRegistry,
    new_callback: Callable[..., Callback],
    record_property: Callable[[str, object], None],
) -> None:
    """Every zaak created while Open Notificaties is down reaches the subscriber once it is back."""
    callback = new_callback()
    make_abonnement(opennotificaties, registry, callback.url, "zaken", {"bronorganisatie": TEST_CATALOGUS_RSIN})
    openzaak = per_thread(lambda: openzaak_client(podiumd_env, ZGW_CLIENT_ID, ZGW_STORE_KEY, run_tag))
    zaaktype = str(test_zaaktype["url"])
    before = cluster_state(podiumd_env)
    start = time.time()
    calls = {"oz_zaak_create": lambda: make_zaak(openzaak(), registry, zaaktype)}
    with watched_load(podiumd_env, urls, ["openzaak"], calls, workers=2, pause=1) as (load, watch):
        load.run_for(CALM)
        with component_down(podiumd_env, http, "opennotificaties"):
            down = time.time()
            load.run_for(OUTAGE)
        back = time.time()
        load.run_for(CALM)
    record_property("report", load_report(load, watch, start))
    assert [*failures(load.attempts, start), *problems(watch)] == []
    zaken = [str(cast("JsonObject", a.result)["url"]) for a in load.attempts]

    def undelivered() -> list[str]:
        received = callback.received()
        return [z for z in zaken if not any(notification("zaken", "zaak", "create", z)(e) for e in received)]

    with suppress(WaitTimeoutError):
        wait_until(lambda: not undelivered(), timeout=DELIVERY_TIMEOUT, interval=10, description="every notificatie")
    record_property("outage_seconds", round(back - down))
    record_property("delivered_seconds_after_restart", round(time.time() - back))
    lost = undelivered()
    assert lost == [], f"{len(lost)} of {len(zaken)} notificaties lost"
    deployment = podiumd_env.deployment_for("opennotificaties")
    assert disruptions(before, cluster_state(podiumd_env), {deployment}) == []


type Sent = tuple[requests.Session, str, str]


def sender(env: Environment, registry: ResourceRegistry) -> Callable[[], Sent]:
    """Return a call that submits the test form anonymously: its session, submission uuid and status URL."""
    base_url = env.profile.urls["openformulieren"]

    def send() -> Sent:
        session = env.session()
        submission, headers = start_submission(session, base_url, TEST_FORM)
        forget_submission(env, registry, str(submission["id"]))
        data = {"klacht_omschrijving": registry.tagged("klacht"), **NAW_DATA}
        status_url = send_submission(session, submission, headers, data, timeout=COMPLETE_TIMEOUT)
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
        status = submission_result(session, status_url, submission, timeout=timeout)
        wait_for_registration(env, submission, timeout=timeout)
        registered_zaak(env, openzaak, registry, status)

    lost: list[str] = []
    for attempt in attempts:
        try:
            register(cast("Sent", attempt.result))
        except AssertionError as exc:
            lost.append(f"sent at +{attempt.start - since:.0f}s: {exc}")
    return lost


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
    worker = worker_deployment(podiumd_env, "openformulieren")
    if worker is None:
        pytest.skip(f"no worker Deployment of openformulieren on {podiumd_env.profile.name}")
    before = cluster_state(podiumd_env)
    start = time.time()
    calls = {"of_submit": sender(podiumd_env, registry)}
    with watched_load(podiumd_env, urls, ["openzaak"], calls, workers=2, pause=2) as (load, watch):
        load.run_for(CALM)
        with scaled(podiumd_env.kube, worker, 0):
            load.run_for(OUTAGE)
        back = time.time()
        load.run_for(CALM)
    record_property("report", load_report(load, watch, start))
    assert [*failures(load.attempts, start), *problems(watch)] == []
    lost = unregistered(podiumd_env, openzaak, registry, load.attempts, start)
    record_property("registered_seconds_after_restart", round(time.time() - back))
    assert lost == [], f"{len(lost)} of {len(load.attempts)} submissions not registered"
    assert disruptions(before, cluster_state(podiumd_env), {worker}) == []


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
    pods = [pod for pod in podiumd_env.items("pods") if pod_workload(pod) in names]
    assert pods, "no Keycloak pod"
    workload = str(pod_workload(pods[0]))
    record_property("keycloak_pods", len(pods))
    before = cluster_state(podiumd_env)
    with watched_load(podiumd_env, urls, ["kiss"], calls, workers=2, pause=1) as (load, watch):
        load.run_for(CALM)
        deleted = time.time()
        replace_pod(podiumd_env, pods[0], KEYCLOAK_RECOVERY)
        load.run_for(CALM)
    record_property("report", load_report(load, watch, deleted))
    recovered = {
        name: recovery_seconds([attempt for attempt in load.attempts if attempt.name == name], deleted)
        for name in calls
    }
    record_property("recovery_seconds", recovered)
    assert None not in recovered.values(), f"not recovered: {recovered}"
    assert problems(watch) == []
    assert disruptions(before, cluster_state(podiumd_env), {workload}) == []
