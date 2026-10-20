"""ZaakBrug: ZDS 1.2 messages answer through the translate endpoints."""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.responses import expect_status
from podiumd_tests.zaakbrug import ZDS
from podiumd_tests.zaakbrug import genereer_zaak_identificatie
from podiumd_tests.zaakbrug import soap_action
from podiumd_tests.zaakbrug import zaak_identificatie

if TYPE_CHECKING:
    import requests

pytestmark = [pytest.mark.component, pytest.mark.requires("zaakbrug")]


def test_genereer_zaak_identificatie(http: requests.Session, urls: dict[str, str]) -> None:
    """genereerZaakIdentificatie_Di02 answers a new zaak identificatie (stored in ZaakBrug, not in Open Zaak)."""
    response = http.post(
        urls["zaakbrug"] + ZDS + "/VrijBericht",
        data=genereer_zaak_identificatie(datetime.now(UTC)),
        headers=soap_action("genereerZaakIdentificatie_Di02"),
    )
    assert zaak_identificatie(expect_status(response, HTTPStatus.OK).text)
