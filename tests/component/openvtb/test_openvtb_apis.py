"""IN-3500: Open VTB with only its Berichten API; podiumd's settings module shuts the Verzoeken and Taken APIs.

Open VTB 0.2.0 lets any token or OIDC caller use every API, so podiumd's openvtb.conf.podiumd_berichten answers 404
to their paths in a middleware and switches the Taken beat task off (helm-charts #749). Where an API is served, the
tests of its shutting skip; the API's own tests (test_openvtb.py) skip where it is shut.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.hygiene import cluster_names
from podiumd_tests.mock_server import in_cluster_statuses
from podiumd_tests.seed.openvtb import API_LISTS
from podiumd_tests.seed.openvtb import TAKEN_TASK
from podiumd_tests.seed.openvtb import enabled_schedules
from podiumd_tests.seed.openvtb import page_statuses
from podiumd_tests.seed.openvtb import served_apis

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("openvtb", "cluster"),
    pytest.mark.source("Jira IN-3500", "Open VTB's Berichten flow on, its Verzoeken and Taken flows off."),
]

SHUT = ("verzoeken", "taken")


@pytest.fixture(scope="module", name="served")
def fixture_served(podiumd_env: Environment) -> set[str]:
    """The Open VTB APIs this environment serves."""
    return served_apis(podiumd_env)


def skip_where_served(apis: set[str], api: str) -> None:
    """Skip where Open VTB serves the API: its shutting is not switched on here."""
    if api in apis:
        pytest.skip(f"Open VTB serves its {api} API here: its settings module is not openvtb.conf.podiumd_berichten")


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("api", SHUT)
@pytest.mark.scenario("""
    Given Open VTB with its Verzoeken and Taken APIs shut
    When a client with a valid Open VTB token calls a Verzoeken or Taken endpoint at Open VTB's public address
    Then Open VTB answers that the endpoint does not exist
""")
def test_shut_api_is_not_found(  # the call's parts
    http: requests.Session,
    podiumd_env: Environment,
    openvtb_berichten: ApiClient,
    served: set[str],
    api: str,
    method: str,
) -> None:
    """A shut API's endpoint answers 404 to a valid token, for reading and for creating."""
    skip_where_served(served, api)
    url = podiumd_env.profile.urls["openvtb"] + API_LISTS[api]
    body = {} if method == "POST" else None
    response = http.request(method, url, headers=openvtb_berichten.headers(), json=body)
    assert response.status_code == HTTPStatus.NOT_FOUND, f"{method} {url}: {response.status_code}"


@pytest.mark.parametrize("api", SHUT)
@pytest.mark.scenario("""
    Given Open VTB with its Verzoeken and Taken APIs shut
    When a pod in Open VTB's namespace calls a Verzoeken or Taken endpoint on Open VTB's Service with a valid token
    Then Open VTB answers that the endpoint does not exist, for reading and for creating
""")
def test_shut_api_is_not_found_inside_the_cluster(
    podiumd_env: Environment,
    need_bootstrap: Callable[..., None],
    openvtb_berichten: ApiClient,
    served: set[str],
    api: str,
) -> None:
    """From the mock server's pod, a shut API's endpoint on each Service name answers 404 to GET and POST."""
    skip_where_served(served, api)
    need_bootstrap("infra-mock-server")
    urls = [base + API_LISTS[api] for base in cluster_names(podiumd_env, "openvtb")]
    if not urls:
        pytest.fail("Open VTB's Deployment has no Service")
    token = {"Authorization": openvtb_berichten.headers()["Authorization"]}
    found = {method: in_cluster_statuses(podiumd_env, urls, token, method) for method in ("GET", "POST")}
    wrong = {
        method: {url: status for url, status in statuses.items() if status != HTTPStatus.NOT_FOUND}
        for method, statuses in found.items()
    }
    assert wrong == {"GET": {}, "POST": {}}


@pytest.mark.scenario("""
    Given Open VTB, with or without its Verzoeken and Taken APIs
    When an administrator opens the admin pages of berichten, verzoeken and taken, the index pages and the schema
    Then every page renders without a server error
""")
def test_pages_render(podiumd_env: Environment) -> None:
    """No admin page, index page or the Berichten schema answers 500 (e.g. NoReverseMatch of a shut API's URL)."""
    statuses = page_statuses(podiumd_env)
    assert {path: status for path, status in statuses.items() if status >= HTTPStatus.INTERNAL_SERVER_ERROR} == {}
    assert statuses["/berichten/api/v1/openapi.yaml"] == HTTPStatus.OK


@pytest.mark.scenario("""
    Given Open VTB with its Taken API shut
    Then its beat does not send the reminder and expired events of taken
""")
def test_shut_taken_send_no_events(podiumd_env: Environment, served: set[str]) -> None:
    """The periodic task send_taak_events is off: it sends Taken CloudEvents for taken that are still in the database."""
    skip_where_served(served, "taken")
    assert enabled_schedules(podiumd_env, TAKEN_TASK) == [], (
        "Open VTB's beat still runs send_taak_events: taken in the database get reminder and expired events"
    )
