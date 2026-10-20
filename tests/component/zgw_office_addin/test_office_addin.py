"""ZGW Office add-in: the manifests point to the public host, and the backend refuses a forged token."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import pytest

from podiumd_tests.auth.zgw_jwt import unsigned_jwt
from podiumd_tests.office_addin import BACKEND
from podiumd_tests.office_addin import MANIFESTS
from podiumd_tests.office_addin import UNREPLACED_URL
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

pytestmark = [pytest.mark.component, pytest.mark.requires("zgw-office-addin")]


@pytest.mark.parametrize("manifest", MANIFESTS)
def test_manifest_points_to_the_public_host(http: requests.Session, urls: dict[str, str], manifest: str) -> None:
    """The manifest loads the add-in from the public host (common.frontendUrl), not from localhost."""
    text = expect_status(http.get(urls["zgw-office-addin"] + manifest), HTTPStatus.OK).text
    assert f"https://{urlsplit(urls['zgw-office-addin']).netloc}/" in text
    assert UNREPLACED_URL not in text


def test_backend_refuses_an_unsigned_token(http: requests.Session, urls: dict[str, str]) -> None:
    """A token without signature gets no zaak lookup: 401 or 403, not 404 (looked up) or 5xx."""
    response = http.get(
        f"{urls['zgw-office-addin']}{BACKEND}/zaken/ptest-unknown",
        headers={"Authorization": f"Bearer {unsigned_jwt({'preferred_username': 'ptest-forged', 'name': 'ptest'})}"},
    )
    assert response.status_code in REFUSED, describe(response)
