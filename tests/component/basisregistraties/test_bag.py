"""BAG adressen through the api-proxy, as Open Formulieren and Open Inwoner look them up.

Ported from podiumd-minikube test_api_proxy.py. Dam 1, Amsterdam is in the BAG and in
podiumd-minikube's WireMock stubs.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import bag_adres
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

pytestmark = [pytest.mark.component, pytest.mark.requires("api-proxy")]

DAM_1 = "0363200003761447"


def test_adres_by_nummeraanduiding(http: requests.Session, urls: dict[str, str]) -> None:
    """A nummeraanduiding gives its adres: street, number, postcode and place."""
    adres = expect_status(bag_adres(http, urls["api-proxy"], DAM_1), HTTPStatus.OK).json()
    assert adres["nummeraanduidingIdentificatie"] == DAM_1
    assert (adres["openbareRuimteNaam"], adres["huisnummer"], adres["postcode"], adres["woonplaatsNaam"]) == (
        "Dam",
        1,
        "1012JS",
        "Amsterdam",
    )
