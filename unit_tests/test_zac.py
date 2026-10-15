"""Unit tests for the ZAC REST helpers."""

import requests

from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import inrichtingscheck_problems


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


def _check(**fields):
    passing = {
        "statustypeIntakeAanwezig": True,
        "aantalInitiatorroltypen": 1,
        "aantalBehandelaarroltypen": 1,
        "besluittypeAanwezig": False,
        "resultaattypesMetVerplichtBesluit": [],
        "isZaakspecifiekeAutorisatieEigenschapAanwezig": False,
        "isZaakspecifiekeAutorisatieRoltypeAanwezig": False,
        "heeftWaarschuwingen": False,
        "valide": True,
    }
    return {**passing, **fields}


def test_inrichtingscheck_passes_without_the_optional_zaakspecifieke_autorisatie():
    assert inrichtingscheck_problems(_check()) == []


def test_inrichtingscheck_names_a_missing_behandelaar_roltype():
    assert inrichtingscheck_problems(_check(aantalBehandelaarroltypen=0, valide=False)) == [
        "aantalBehandelaarroltypen=0"
    ]


def test_inrichtingscheck_needs_a_besluittype_only_for_a_resultaattype_with_verplicht_besluit():
    check = _check(resultaattypesMetVerplichtBesluit=["Toegekend"], valide=False)
    assert inrichtingscheck_problems(check) == ["besluittypeAanwezig"]


def test_inrichtingscheck_fails_on_zacs_warnings():
    check = _check(isZaakspecifiekeAutorisatieRoltypeAanwezig=True, heeftWaarschuwingen=True)
    assert inrichtingscheck_problems(check) == ["heeftWaarschuwingen"]


def test_inrichtingscheck_falls_back_to_zacs_verdict():
    assert inrichtingscheck_problems(_check(valide=False)) == ["valide"]
