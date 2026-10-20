"""OpenBao hardening: its Prometheus metrics must not be readable without a token.

OpenBao's /v1/sys/metrics exposes mount paths, token and lease counts and seal/HA state. On a listener with
unauthenticated_metrics_access the public host would serve them to anyone; this asserts a token is required.
Skips where the profile has no OpenBao URL.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.responses import describe

if TYPE_CHECKING:
    import requests

pytestmark = [pytest.mark.component, pytest.mark.requires("openbao")]

REFUSED = {HTTPStatus.BAD_REQUEST, HTTPStatus.FORBIDDEN, HTTPStatus.UNAUTHORIZED}


@pytest.mark.parametrize("query", ["", "?format=prometheus"])
def test_metrics_need_a_token(http: requests.Session, urls: dict[str, str], query: str) -> None:
    """Without a token the metrics endpoint is refused, not 200 with metrics."""
    response = http.get(f"{urls['openbao']}/v1/sys/metrics{query}")
    assert response.status_code in REFUSED, describe(response)
