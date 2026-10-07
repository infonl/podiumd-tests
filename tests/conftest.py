"""Environment tests: they need a live environment; run them with `podiumd-tests run`."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.browser import context_args
from podiumd_tests.browser import launch_args

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment

pytest_plugins = ["podiumd_tests.pytest_plugin"]


# pytest-playwright's own fixtures, extended here: a conftest overrides a plugin's fixture.
@pytest.fixture(scope="session")
def browser_type_launch_args(
    browser_type_launch_args: dict[str, object], podiumd_env: Environment
) -> dict[str, object]:
    """Chromium reaches the profile hosts as the HTTP sessions do."""
    args = [*cast("list[str]", browser_type_launch_args.get("args") or []), *launch_args(podiumd_env)]
    return {**browser_type_launch_args, "args": args}


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict[str, object], podiumd_env: Environment) -> dict[str, object]:
    """Every page starts with the profile's TLS settings, in Dutch."""
    return {**browser_context_args, **context_args(podiumd_env), "locale": "nl-NL"}
