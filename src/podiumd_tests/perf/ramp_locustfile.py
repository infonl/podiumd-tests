"""Locust ramp of tests/perf/test_ramp_perf.py: ApiUser's calls at user counts that step up.

A separate locustfile: Locust applies a LoadTestShape to every run of the file that defines it. Each call's stats
are labelled with the step's users (stats.labelled). The locustfile module is imported as a module, so Locust
finds only RampUser here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from locust import LoadTestShape
from locust import events

from podiumd_tests.perf import locustfile
from podiumd_tests.perf.runs import ramp_steps
from podiumd_tests.perf.runs import ramp_users
from podiumd_tests.perf.stats import labelled

if TYPE_CHECKING:
    from argparse import ArgumentParser


@events.init_command_line_parser.add_listener
def _arguments(parser: ArgumentParser) -> None:
    parser.add_argument("--podiumd-steps", required=True, help="user counts of the steps, e.g. 2,4,8,16")
    parser.add_argument("--podiumd-step-time", type=float, required=True, help="seconds per step")


class RampUser(locustfile.ApiUser):
    """ApiUser whose stats carry the users of the step its call started in."""

    def stats_name(self, name: str) -> str:
        """Return the call's name labelled with the step's users."""
        return labelled(name, self.environment.runner.target_user_count)  # pyright: ignore[reportOptionalMemberAccess]


class StepShape(LoadTestShape):
    """--podiumd-steps users, each step --podiumd-step-time seconds, all of a step's users started at once."""

    def tick(self) -> tuple[int, float] | None:
        """Return the users and spawn rate of the current step; None after the last."""
        options = self.runner.environment.parsed_options  # pyright: ignore[reportOptionalMemberAccess]
        users = ramp_users(ramp_steps(options.podiumd_steps), options.podiumd_step_time, self.get_run_time())
        return None if users is None else (users, users)
