"""Unit tests for the ZAC REST helpers."""

import requests

from podiumd_tests.zac import create_zaak


def test_create_zaak_reads_the_zaak_when_zac_answers_only_its_identificatie(fake_http):
    fake_http(
        {
            "POST /rest/zaken/zaak": (200, {"identificatie": "ZAAK-1"}),
            "GET /rest/zaken/zaak/id/ZAAK-1": (200, {"identificatie": "ZAAK-1", "uuid": "u-1"}),
        }
    )
    parameters = {"zaaktype": {"uuid": "zt"}, "defaultGroepId": "g"}
    zaak = create_zaak(requests.Session(), "https://zac.test", parameters, omschrijving="x")
    assert zaak["uuid"] == "u-1"
