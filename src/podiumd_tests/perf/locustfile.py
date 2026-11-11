"""Locust users of the perf tier: reads, writes and searches, with the suite's own sessions and credentials.

tests/perf starts Locust on this file with --podiumd-env and --podiumd-run-tag. Timings reach Locust
through its request event, so host-header mode, the CA file and the tokens work as in the other tiers.
A write's cleanup runs after its timing, tagged with the run tag so sweep finds what a crash leaves.
"""

from __future__ import annotations

import time

from functools import partial
from typing import TYPE_CHECKING

from locust import User
from locust import constant
from locust import events
from locust import task

from podiumd_tests.auth.keycloak import discovery_url
from podiumd_tests.auth.keycloak_admin import realm_of
from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.basisregistraties import brp_personen
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.clients.platform import objecten_client
from podiumd_tests.clients.platform import openklant_client
from podiumd_tests.config import default_envs_dir
from podiumd_tests.config import load_profile
from podiumd_tests.environment import Environment
from podiumd_tests.kcc import vac_data
from podiumd_tests.oidc import challenge_session
from podiumd_tests.perf.zgw_calls import Call
from podiumd_tests.perf.zgw_calls import Prepared
from podiumd_tests.perf.zgw_calls import opennotificaties_calls
from podiumd_tests.perf.zgw_calls import openzaak_calls
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.objecten import make_object
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openklant import make_klantcontact
from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.registry import ResourceRegistry
from podiumd_tests.zac import zac_session

if TYPE_CHECKING:
    from argparse import ArgumentParser
    from collections.abc import Callable

    from locust.env import Environment as LocustEnvironment


# A word the volume corpus, KISS's kennisbank and the portal's products all use.
SEARCH_TERM = "aanvraag"


@events.init_command_line_parser.add_listener
def _arguments(parser: ArgumentParser) -> None:
    parser.add_argument("--podiumd-env", required=True, help="environment profile name")
    parser.add_argument("--podiumd-run-tag", required=True, help="run tag of what the writes create")


@events.init.add_listener
def _on_init(environment: LocustEnvironment, **_kwargs: object) -> None:
    profile = load_profile(environment.parsed_options.podiumd_env, default_envs_dir())
    ApiUser.env_under_test = Environment(profile)
    ApiUser.run_tag = environment.parsed_options.podiumd_run_tag


def _openklant_calls(env: Environment) -> dict[str, Call]:
    openklant = openklant_client(env)
    return {
        "ok2_partijen": lambda _registry: openklant.request("GET", "partijen", 200),
        "ok2_klantcontact_create": lambda registry: make_klantcontact(openklant, registry),
        # KISS and the portal find a person's partij by BSN.
        "ok2_partij_by_bsn": lambda _registry: openklant.request(
            "GET", "partij-identificatoren", 200, params={"partijIdentificatorObjectId": random_bsn()}
        ),
    }


def _objecten_calls(env: Environment) -> dict[str, Call]:
    """VAC objects: harmless to create, as no app acts on a new one (a productaanvraag would start a zaak)."""
    objecten = objecten_client(env)
    vac = objecttype_url(env, "VAC")
    query = {"type": vac, "data_attr": f"vraag__icontains__{SEARCH_TERM}", "pageSize": "20"}
    return {
        "obj_vac_create": lambda registry: make_object(objecten, registry, vac, vac_data(registry.tagged("perf-vac"))),
        "obj_vac_search": lambda _registry: objecten.request("GET", "objects", 200, params=query),
    }


def _search_calls(env: Environment) -> dict[str, Call]:
    """Return the searches users do: ZAC's (Solr) and KISS's (Elasticsearch) logged in, the portal's anonymous."""
    urls = env.profile.urls
    calls: dict[str, Call] = {}
    if "zac" in urls:
        zac = zac_session(env, ADMIN.username, env.credentials.get(ADMIN.store_key))
        query = {"page": 0, "rows": 10, "type": "ZAAK", "zoeken": {"ALLE": SEARCH_TERM}}
        calls["zac_search"] = lambda _registry: expect_status(
            zac.put(f"{urls['zac']}/rest/zoeken/list", json=query), 200
        )
    if "kiss" in urls:
        kiss = challenge_session(env, urls["kiss"], KCC.username, env.credentials.get(KCC.store_key))
        body = {"query": SEARCH_TERM, "page": 1, "filters": []}
        calls["kiss_search"] = lambda _registry: expect_status(kiss.post(f"{urls['kiss']}/api/search", json=body), 200)
    if "openinwoner" in urls:
        portal = env.session()
        search = f"{urls['openinwoner']}/search/"
        calls["oi_search"] = lambda _registry: expect_status(portal.get(search, params={"query": SEARCH_TERM}), 200)
    return calls


class ApiUser(User):
    """One user: each round makes every call the environment has, then waits 1 s."""

    wait_time = constant(1)
    env_under_test: Environment
    run_tag: str

    def __init__(self, environment: LocustEnvironment) -> None:
        super().__init__(environment)
        self.calls = self._calls()

    @task
    def round_of_calls(self) -> None:
        """Every call once, timed without its setup; what a call created is deleted after its timing."""
        for name, call in self.calls.items():
            registry = ResourceRegistry(self.run_tag)
            try:
                self._timed(name, call, registry)
            finally:
                # Also when Locust stops the user (GreenletExit) right after a write.
                registry.cleanup()

    def _timed(self, name: str, call: Call | Prepared, registry: ResourceRegistry) -> None:
        """Make the call and report its time and outcome to Locust; a setup failure counts as a failed call."""
        error = None
        timed: Callable[[], object]
        if isinstance(call, tuple):
            prepare, run = call
            try:
                prepared = prepare(registry)
            except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught  # Locust counts it
                self.environment.events.request.fire(
                    request_type="API", name=name, response_time=0, response_length=0, exception=exc
                )
                return
            timed = partial(run, prepared)
        else:
            timed = partial(call, registry)
        started = time.perf_counter()
        try:
            timed()
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught  # Locust counts it
            error = exc
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.environment.events.request.fire(
            request_type="API", name=name, response_time=elapsed_ms, response_length=0, exception=error
        )

    def _calls(self) -> dict[str, Call | Prepared]:
        """Return the calls of podiumd_tests.perf.runs.ENDPOINTS whose component the environment has."""
        env = self.env_under_test
        http = env.session(cookies=False)
        urls = env.profile.urls
        calls: dict[str, Call | Prepared] = {}
        if "openzaak" in urls:
            calls |= openzaak_calls(env)
        if "openklant" in urls:
            calls |= _openklant_calls(env)
        if "opennotificaties" in urls:
            calls |= opennotificaties_calls(env)
        if "objecten" in urls:
            calls |= _objecten_calls(env)
        if "api-proxy" in urls:
            query = {"type": "RaadpleegMetBurgerservicenummer", "burgerservicenummer": [EREBOS], "fields": ["naam"]}
            calls["brp_persoon"] = lambda _registry: expect_status(brp_personen(http, urls["api-proxy"], query), 200)
        if "keycloak" in urls:
            discovery = discovery_url(urls["keycloak"], realm_of(env))
            calls["kc_discovery"] = lambda _registry: expect_status(http.get(discovery), 200)
        return calls | _search_calls(env)
