"""Locust users of the perf tier: reads, writes and searches, with the suite's own sessions and credentials.

tests/perf starts Locust on this file with --podiumd-env and --podiumd-run-tag. Timings reach Locust
through its request event, so host-header mode, the CA file and the tokens work as in the other tiers.
A write's cleanup runs after its timing, tagged with the run tag so sweep finds what a crash leaves.
"""

from __future__ import annotations

import time

from typing import TYPE_CHECKING

from locust import User
from locust import constant
from locust import events
from locust import task

from podiumd_tests.auth.keycloak import discovery_url
from podiumd_tests.auth.keycloak import form_login
from podiumd_tests.auth.keycloak_admin import realm_of
from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.basisregistraties import brp_personen
from podiumd_tests.bootstrap.names import TEST_ZAAKTYPE
from podiumd_tests.bootstrap.names import ZGW_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_STORE_KEY
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.clients.platform import openklant_client
from podiumd_tests.clients.platform import openzaak_client
from podiumd_tests.config import default_envs_dir
from podiumd_tests.config import load_profile
from podiumd_tests.environment import Environment
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openklant import make_klantcontact
from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.openzaak import BSN_FILTER
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.registry import ResourceRegistry
from podiumd_tests.zac import zac_session

if TYPE_CHECKING:
    from argparse import ArgumentParser
    from collections.abc import Callable

    from locust.env import Environment as LocustEnvironment

# A word the volume corpus, KISS's kennisbank and the portal's products all use.
SEARCH_TERM = "aanvraag"
type Call = Callable[[ResourceRegistry], object]


@events.init_command_line_parser.add_listener
def _arguments(parser: ArgumentParser) -> None:
    parser.add_argument("--podiumd-env", required=True, help="environment profile name")
    parser.add_argument("--podiumd-run-tag", required=True, help="run tag of what the writes create")


@events.init.add_listener
def _environment(environment: LocustEnvironment, **_kwargs: object) -> None:
    profile = load_profile(environment.parsed_options.podiumd_env, default_envs_dir())
    ApiUser.env_under_test = Environment(profile)
    ApiUser.run_tag = environment.parsed_options.podiumd_run_tag


def _openzaak_calls(env: Environment) -> dict[str, Call]:
    openzaak = openzaak_client(env, ZGW_CLIENT_ID, ZGW_STORE_KEY, "perf")
    zaaktype = str(openzaak.list(f"{CATALOGI}/zaaktypen", {"identificatie": TEST_ZAAKTYPE})[0]["url"])
    return {
        "oz_zaken": lambda _r: openzaak.request("GET", f"{ZAKEN}/zaken", 200, params={"pageSize": "20"}),
        "oz_zaaktypen": lambda _r: openzaak.request("GET", f"{CATALOGI}/zaaktypen", 200),
        "oz_zaak_create": lambda registry: make_zaak(openzaak, registry, zaaktype),
        # Mijn zaken: the zaken of one inwoner, a join over every zaak's rollen.
        "oz_zaken_by_bsn": lambda _r: openzaak.request("GET", f"{ZAKEN}/zaken", 200, params={BSN_FILTER: random_bsn()}),
    }


def _openklant_calls(env: Environment) -> dict[str, Call]:
    openklant = openklant_client(env)
    return {
        "ok2_partijen": lambda _r: openklant.request("GET", "partijen", 200),
        "ok2_klantcontact_create": lambda registry: make_klantcontact(openklant, registry),
        # KISS and the portal find a person's partij by BSN.
        "ok2_partij_by_bsn": lambda _r: openklant.request(
            "GET", "partij-identificatoren", 200, params={"partijIdentificatorObjectId": random_bsn()}
        ),
    }


def _search_calls(env: Environment) -> dict[str, Call]:
    """Searches as users do them: ZAC's (Solr) and KISS's (Elasticsearch) logged in, the portal's anonymous."""
    urls = env.profile.urls
    calls: dict[str, Call] = {}
    if "zac" in urls:
        zac = zac_session(env, ADMIN.username, env.credentials.get(ADMIN.store_key))
        query = {"page": 0, "rows": 10, "type": "ZAAK", "zoeken": {"ALLE": SEARCH_TERM}}
        calls["zac_search"] = lambda _r: expect_status(zac.put(urls["zac"] + "/rest/zoeken/list", json=query), 200)
    if "kiss" in urls:
        kiss = env.session()
        form_login(
            kiss, urls["kiss"] + "/api/challenge?returnUrl=%2F", KCC.username, env.credentials.get(KCC.store_key)
        )
        body = {"query": SEARCH_TERM, "page": 1, "filters": []}
        calls["kiss_search"] = lambda _r: expect_status(kiss.post(urls["kiss"] + "/api/search", json=body), 200)
    if "openinwoner" in urls:
        portal = env.session()
        search = urls["openinwoner"] + "/search/"
        calls["oi_search"] = lambda _r: expect_status(portal.get(search, params={"query": SEARCH_TERM}), 200)
    return calls


class ApiUser(User):
    """One user: each round makes every call the environment has, then waits 1 s."""

    wait_time = constant(1)
    env_under_test: Environment
    run_tag: str

    def __init__(self, environment: LocustEnvironment) -> None:
        super().__init__(environment)
        self.calls = self._calls()

    def _calls(self) -> dict[str, Call]:
        """The calls of podiumd_tests.perf.ENDPOINTS whose component the environment has."""
        env = self.env_under_test
        http = env.session(cookies=False)
        urls = env.profile.urls
        calls: dict[str, Call] = {}
        if "openzaak" in urls:
            calls |= _openzaak_calls(env)
        if "openklant" in urls:
            calls |= _openklant_calls(env)
        if "api-proxy" in urls:
            query = {"type": "RaadpleegMetBurgerservicenummer", "burgerservicenummer": [EREBOS], "fields": ["naam"]}
            calls["brp_persoon"] = lambda _r: expect_status(brp_personen(http, urls["api-proxy"], query), 200)
        if "keycloak" in urls:
            discovery = discovery_url(urls["keycloak"], realm_of(env))
            calls["kc_discovery"] = lambda _r: expect_status(http.get(discovery), 200)
        return calls | _search_calls(env)

    @task
    def round_of_calls(self) -> None:
        """Every call once, timed; what a write created is deleted after its timing."""
        for name, call in self.calls.items():
            registry = ResourceRegistry(self.run_tag)
            try:
                self._timed(name, call, registry)
            finally:
                # Also when Locust stops the user (GreenletExit) right after a write.
                registry.cleanup()

    def _timed(self, name: str, call: Call, registry: ResourceRegistry) -> None:
        """Make the call and report its time and outcome to Locust."""
        started = time.perf_counter()
        error = None
        try:
            call(registry)
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught  # Locust counts it
            error = exc
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.environment.events.request.fire(
            request_type="API", name=name, response_time=elapsed_ms, response_length=0, exception=error
        )
