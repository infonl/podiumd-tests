"""Does Open Zaak accept a ZGW JWT? Ported from TA/EX smoke 01-zgw-auth.

Read-only. The data checks of 01 need a test zaaktype: phase 3 factories.
The client is settings.zgw_client_id with secret zgw_client_secret.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.zgw_jwt import zgw_headers
from podiumd_tests.auth.zgw_jwt import zgw_jwt
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from podiumd_tests.credentials import SecretResolver
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.smoke, pytest.mark.requires("openzaak")]


@pytest.fixture(name="client_id")
def fixture_client_id(podiumd_env: Environment, credentials: SecretResolver) -> str:
    """ZGW client id of the profile; skip when the environment has no ZGW client."""
    client_id = podiumd_env.profile.settings.get("zgw_client_id")
    if not client_id or not credentials.configured("zgw_client_secret"):
        pytest.skip("no settings.zgw_client_id or no secret zgw_client_secret: add both to the profile")
    return client_id


def _get(http: requests.Session, url: str, token: str) -> requests.Response:
    return http.get(url, headers=zgw_headers(token))


@pytest.mark.parametrize("path", ["/catalogi/api/v1/catalogussen", "/catalogi/api/v1/zaaktypen"])
def test_jwt_is_accepted(
    http: requests.Session, urls: dict[str, str], credentials: SecretResolver, client_id: str, path: str
) -> None:
    """A token signed with the client's secret reads a paginated list."""
    response = _get(http, urls["openzaak"] + path, zgw_jwt(client_id, credentials.get("zgw_client_secret")))
    expect_status(response, HTTPStatus.OK)
    body = response.json()
    assert isinstance(body["results"], list)
    assert isinstance(body["count"], int)


def test_jwt_with_wrong_secret_is_refused(http: requests.Session, urls: dict[str, str], client_id: str) -> None:
    """A token with a wrong signature is refused."""
    response = _get(http, urls["openzaak"] + "/catalogi/api/v1/catalogussen", zgw_jwt(client_id, "ptest-wrong-secret"))
    expect_status(response, *REFUSED)
