"""Continuity: a stopped component answers no more, the others stay up, and it comes back.

Ported from TA regression 89, 124 and 144. Each test scales the component's main deployment to 0
and restores it afterwards.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import requests

from podiumd_tests.components import COMPONENTS
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.responses import get_root
from podiumd_tests.responses import is_server_error
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import scaled

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.integration, pytest.mark.destructive, pytest.mark.requires("cluster")]

STOPPED = ("openzaak", "openformulieren", "openklant", "opennotificaties", "openinwoner", "ita", "omc")
TIMEOUT = 10.0


def answers(http: requests.Session, url: str) -> bool:
    """Whether the root answers without a server error."""
    try:
        return not is_server_error(get_root(http, url, TIMEOUT))
    except requests.RequestException:
        return False


@pytest.mark.parametrize("component", [requiring(c, c) for c in STOPPED])
def test_stopped_component_harms_no_other(
    http: requests.Session, urls: dict[str, str], podiumd_env: Environment, component: str
) -> None:
    """While the component is stopped its root fails and every other root answers (TA reg-89, 124, 144)."""
    others = [c for c in sorted(urls) if c != component and c in COMPONENTS and answers(http, urls[c])]
    with scaled(podiumd_env.kube, podiumd_env.deployment_for(component), 0):
        wait_until(lambda: not answers(http, urls[component]), timeout=120, description=f"{component} stopped")
        assert [c for c in others if not answers(http, urls[c])] == []
    wait_until(lambda: answers(http, urls[component]), timeout=300, description=f"{component} answers again")
