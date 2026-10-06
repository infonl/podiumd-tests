"""Does Open Zaak accept a ZGW JWT? Ported from TA/EX smoke 01-zgw-auth.

Read-only. The data checks of 01 (test catalogus domein, test zaaktype) move
to phase 2, where bootstrap seeds that data. The client comes from the
profile: settings.zgw_client_id and secret zgw_client_secret.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.zgw_jwt import zgw_jwt

if TYPE_CHECKING:
    import requests

    from podiumd_tests.credentials import SecretResolver
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.smoke, pytest.mark.requires("openzaak")]

ZGW_HEADERS = {"Accept-Crs": "EPSG:4326", "Content-Crs": "EPSG:4326", "Accept": "application/json"}


@pytest.fixture(name="client_id")
def fixture_client_id(podiumd_env: Environment, credentials: SecretResolver) -> str:
    """ZGW client id of the profile; skip when the environment has no ZGW client."""
    client_id = podiumd_env.profile.settings.get("zgw_client_id")
    if not client_id or not credentials.configured("zgw_client_secret"):
        pytest.skip("no settings.zgw_client_id, or no secret zgw_client_secret (profile or env var)")
    return client_id


def _get(http: requests.Session, url: str, token: str) -> requests.Response:
    return http.get(url, headers={**ZGW_HEADERS, "Authorization": f"Bearer {token}"})


@pytest.mark.parametrize("path", ["/catalogi/api/v1/catalogussen", "/catalogi/api/v1/zaaktypen"])
def test_jwt_is_accepted(
    http: requests.Session, urls: dict[str, str], credentials: SecretResolver, client_id: str, path: str
) -> None:
    """A token signed with the client's secret reads a paginated list."""
    response = _get(http, urls["openzaak"] + path, zgw_jwt(client_id, credentials.get("zgw_client_secret")))
    assert response.status_code == 200, f"{response.url}: HTTP {response.status_code}"
    body = response.json()
    assert isinstance(body["results"], list)
    assert isinstance(body["count"], int)


def test_jwt_with_wrong_secret_is_refused(http: requests.Session, urls: dict[str, str], client_id: str) -> None:
    """A token with a wrong signature is refused."""
    response = _get(http, urls["openzaak"] + "/catalogi/api/v1/catalogussen", zgw_jwt(client_id, "ptest-wrong-secret"))
    assert response.status_code in {401, 403}, f"HTTP {response.status_code}"
