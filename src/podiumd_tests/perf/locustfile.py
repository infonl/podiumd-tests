"""Locust users of the perf tier: TA's read-only API calls, with the suite's own sessions and credentials.

tests/perf starts Locust on this file with --podiumd-env. Timings reach Locust through its request
event, so host-header mode, the CA file and the tokens work as in the other tiers.
"""

from __future__ import annotations

import time

from typing import TYPE_CHECKING

from locust import User
from locust import constant
from locust import events
from locust import task

from podiumd_tests.auth.keycloak import discovery_url
from podiumd_tests.auth.keycloak_admin import realm_of
from podiumd_tests.basisregistraties import brp_personen
from podiumd_tests.bootstrap.names import ZGW_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_STORE_KEY
from podiumd_tests.clients.platform import openklant_client
from podiumd_tests.clients.platform import openzaak_client
from podiumd_tests.config import default_envs_dir
from podiumd_tests.config import load_profile
from podiumd_tests.environment import Environment
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import ZAKEN

if TYPE_CHECKING:
    from argparse import ArgumentParser
    from collections.abc import Callable

    import requests

    from locust.env import Environment as LocustEnvironment

BSN = "999990019"


@events.init_command_line_parser.add_listener
def _arguments(parser: ArgumentParser) -> None:
    parser.add_argument("--podiumd-env", required=True, help="environment profile name")


@events.init.add_listener
def _environment(environment: LocustEnvironment, **_kwargs: object) -> None:
    profile = load_profile(environment.parsed_options.podiumd_env, default_envs_dir())
    ApiUser.env_under_test = Environment(profile)


class ApiUser(User):
    """One inwoner-sized user: each round calls every endpoint the environment has, then waits 1 s."""

    wait_time = constant(1)
    env_under_test: Environment

    def __init__(self, environment: LocustEnvironment) -> None:
        super().__init__(environment)
        self.calls = self._calls()

    def _calls(self) -> dict[str, Callable[[], requests.Response]]:
        """The calls of this user: those of podiumd_tests.perf.ENDPOINTS whose component the environment has."""
        env = self.env_under_test
        http = env.session(cookies=False)
        urls = env.profile.urls
        calls: dict[str, Callable[[], requests.Response]] = {}
        if "openzaak" in urls:
            openzaak = openzaak_client(env, ZGW_CLIENT_ID, ZGW_STORE_KEY, "perf")
            calls["oz_zaken"] = lambda: openzaak.request("GET", f"{ZAKEN}/zaken", 200, params={"pageSize": "20"})
            calls["oz_zaaktypen"] = lambda: openzaak.request("GET", f"{CATALOGI}/zaaktypen", 200)
        if "openklant" in urls:
            openklant = openklant_client(env)
            calls["ok2_partijen"] = lambda: openklant.request("GET", "partijen", 200)
        if "api-proxy" in urls:
            query = {"type": "RaadpleegMetBurgerservicenummer", "burgerservicenummer": [BSN], "fields": ["naam"]}
            calls["brp_persoon"] = lambda: expect_status(brp_personen(http, urls["api-proxy"], query), 200)
        if "keycloak" in urls:
            discovery = discovery_url(urls["keycloak"], realm_of(env))
            calls["kc_discovery"] = lambda: expect_status(http.get(discovery), 200)
        return calls

    @task
    def round_of_calls(self) -> None:
        """Every endpoint once, timed."""
        for name, call in self.calls.items():
            started = time.perf_counter()
            length, error = 0, None
            try:
                length = len(call().content)
            except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught  # Locust counts it
                error = exc
            elapsed_ms = (time.perf_counter() - started) * 1000
            self.environment.events.request.fire(
                request_type="API", name=name, response_time=elapsed_ms, response_length=length, exception=error
            )
