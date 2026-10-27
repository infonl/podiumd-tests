"""Locust user of tests/perf/test_gateway_perf.py: one anonymous scenario of GATEWAY_SCENARIOS, without redirects.

A failure is named after its status code or connection error, so Locust's failures CSV splits them. Locust's stats
restart after --podiumd-warmup seconds.
"""

from __future__ import annotations

import re
import time

from typing import TYPE_CHECKING

import gevent

from locust import User
from locust import constant
from locust import events
from locust import task

from podiumd_tests.config import default_envs_dir
from podiumd_tests.config import load_profile
from podiumd_tests.environment import Environment
from podiumd_tests.perf import GATEWAY_SCENARIOS

if TYPE_CHECKING:
    from argparse import ArgumentParser

    from locust.env import Environment as LocustEnvironment

ASSET = re.compile(r'(?:src|href)="(/[^"]+\.(?:js|css))"')


@events.init_command_line_parser.add_listener
def _arguments(parser: ArgumentParser) -> None:
    parser.add_argument("--podiumd-env", required=True, help="environment profile name")
    parser.add_argument("--podiumd-scenario", required=True, choices=sorted(GATEWAY_SCENARIOS), help="scenario")
    parser.add_argument("--podiumd-warmup", type=float, default=0, help="seconds before the stats restart")


@events.init.add_listener
def _environment(environment: LocustEnvironment, **_kwargs: object) -> None:
    options = environment.parsed_options
    GatewayUser.env_under_test = Environment(load_profile(options.podiumd_env, default_envs_dir()))
    GatewayUser.scenario = options.podiumd_scenario


@events.test_start.add_listener
def _warmup(environment: LocustEnvironment, **_kwargs: object) -> None:
    gevent.spawn_later(environment.parsed_options.podiumd_warmup, environment.stats.reset_all)


class GatewayUser(User):
    """One client with its own connection pool, requesting its scenario without pause."""

    wait_time = constant(0)
    env_under_test: Environment
    scenario: str

    def __init__(self, environment: LocustEnvironment) -> None:
        super().__init__(environment)
        component, path, self.status = GATEWAY_SCENARIOS[self.scenario]
        self.http = self.env_under_test.session(cookies=False)
        root = self.env_under_test.profile.urls[component]
        self.urls = [root + path]
        if self.scenario == "kiss_page":
            self.urls += [root + asset for asset in ASSET.findall(self.http.get(self.urls[0]).text)]

    @task
    def request(self) -> None:
        """The scenario's URLs in order, timed as one request."""
        started = time.perf_counter()
        error = None
        try:
            for url in self.urls:
                response = self.http.get(url, allow_redirects=False)
                expected = self.status if url == self.urls[0] else 200
                if response.status_code != expected:
                    error = RuntimeError(f"HTTP {response.status_code}")
                    break
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught  # Locust counts it
            error = RuntimeError(type(exc).__name__)
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.environment.events.request.fire(
            request_type="GET", name=self.scenario, response_time=elapsed_ms, response_length=0, exception=error
        )
