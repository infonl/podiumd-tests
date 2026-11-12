"""BAG adressen through the api-proxy, as Open Formulieren and Open Inwoner look them up.

Ported from podiumd-minikube test_api_proxy.py.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import BAG_DAM
from podiumd_tests.basisregistraties import bag_adres
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("api-proxy"),
    pytest.mark.source(
        "MK test_api_proxy.py",
        "Checks the api-proxy serves BRP, KvK and BAG on the paths ExternalsPodiumD's apps call.",
    ),
]


@pytest.mark.scenario("""
    Given Dam 1 in Amsterdam is an adres in the BAG
    When its nummeraanduiding is looked up through the api-proxy
    Then the BAG gives street Dam, huisnummer 1, postcode 1012JS and woonplaats Amsterdam
""")
def test_adres_by_nummeraanduiding(http: requests.Session, urls: dict[str, str]) -> None:
    """A nummeraanduiding gives its adres: street, number, postcode and place."""
    adres = expect_status(bag_adres(http, urls["api-proxy"], BAG_DAM), HTTPStatus.OK).json()
    assert adres["nummeraanduidingIdentificatie"] == BAG_DAM
    assert (adres["openbareRuimteNaam"], adres["huisnummer"], adres["postcode"], adres["woonplaatsNaam"]) == (
        "Dam",
        1,
        "1012JS",
        "Amsterdam",
    )
