"""ZAC's build information, which its beheer pages and user menu show, against the deployed image."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.responses import expect_status
from podiumd_tests.workloads import component_versions

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "keycloak", "cluster"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, overig).",
    ),
]


@pytest.mark.scenario("""
    Given ZAC runs from a release image
    When the beheerder opens ZAC's build information
    Then it shows the version of that image, with a commit and a build date
""")
def test_build_information_is_the_deployed_version(
    zac: requests.Session, urls: dict[str, str], podiumd_env: Environment
) -> None:
    """GET /rest/health-check/build-informatie names the version of the zac Deployment's image."""
    deployed = component_versions(podiumd_env, ["zac"]).get("zac")
    if deployed is None:
        pytest.skip("the zac Deployment states no version: no version tag or label")
    response = zac.get(f"{urls['zac']}/rest/health-check/build-informatie")
    build = expect_status(response, HTTPStatus.OK).json()
    assert build["versienummer"] == ".".join(map(str, deployed))
    assert build["commit"]
    assert build["buildDatumTijd"]
