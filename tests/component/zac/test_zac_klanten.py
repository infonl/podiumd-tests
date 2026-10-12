"""ZAC looks up a person in the BRP and a company in KvK through its own REST API.

Ported from TA regression 193. No estate routes ZAC to Open Zaak through Frank!Gateway; rollen
with these identities in Open Zaak are covered by tests/component/openzaak/test_statussen_rollen.py.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.basisregistraties import KVK_TEST_NUMMER
from podiumd_tests.responses import expect_status
from podiumd_tests.zac import person_lookup

if TYPE_CHECKING:
    import requests


pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "keycloak")]


def test_person_lookup(zac: requests.Session, urls: dict[str, str]) -> None:
    """ZAC finds a BRP test-set person by BSN, with the name (TA reg-193)."""
    personen = person_lookup(zac, urls["zac"], EREBOS)
    assert [p["bsn"] for p in personen] == [EREBOS]
    assert "Bultenaar" in str(personen[0]["naam"])


@pytest.mark.tc("INT-004", "INT-005")
def test_company_lookup(zac: requests.Session, urls: dict[str, str]) -> None:
    """ZAC finds the KvK test company's basisprofiel by KvK number (TA reg-193)."""
    url = f"{urls['zac']}/rest/klanten/basisprofiel/{KVK_TEST_NUMMER}"
    bedrijf = expect_status(zac.get(url), HTTPStatus.OK).json()
    assert bedrijf["kvkNummer"] == KVK_TEST_NUMMER
    assert "Test BV Donald" in str(bedrijf.get("statutaireNaam") or bedrijf.get("eersteHandelsnaam"))
