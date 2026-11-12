"""ZAC: the zaakgegevens it refuses, the dates it derives and the communicatiekanalen it offers, through its REST API.

The zaak is of the estate's productaanvraag zaaktype (fixture zac_zaak), or of podiumd-tests' own zaaktype, which has no
servicenorm (fixture zac_eigen_zaak).
"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import section
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import after_period
from podiumd_tests.zac import attempt_zaak
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import wijzig_zaak
from podiumd_tests.zac import zaak_body
from podiumd_tests.zac_beheer import communicatiekanalen

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "openzaak", "keycloak"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, zaak-lifecycle).",
    ),
]

# RestZaakCreateData.toelichting allows 1000 characters.
TOO_LONG_TOELICHTING = "t" * 1001
# Open Zaak's organisatorische eenheid allows a naam of 255 characters.
TOO_LONG_GROEP_NAAM = "g" * 256
# The communicatiekanaal of ZAC's referentietabel that ZAC never offers on a zaak.
E_FORMULIER = "E-formulier"


@pytest.mark.parametrize(
    "ongeldig",
    [
        pytest.param({"communicatiekanaal": None}, id="zonder-communicatiekanaal"),
        pytest.param({"toelichting": TOO_LONG_TOELICHTING}, id="toelichting-te-lang"),
        pytest.param({"groep": TOO_LONG_GROEP_NAAM}, id="groepsnaam-te-lang"),
    ],
)
@pytest.mark.scenario("""
    Given a behandelaar is logged in to ZAC
    When the behandelaar starts a zaak without communicatiekanaal, with a toelichting over 1000 characters, or with a group name over 255 characters
    Then ZAC refuses it as a bad request
    And Open Zaak has no zaak of it
""")
def test_new_zaak_with_invalid_gegevens_is_refused(
    zac: requests.Session,
    urls: dict[str, str],
    zac_parameters: JsonObject,
    openzaak_productaanvraag: ApiClient,
    registry: ResourceRegistry,
    ongeldig: dict[str, object],
) -> None:
    """ZAC answers 400 and creates no zaak."""
    fields = dict(ongeldig)
    if "groep" in fields:
        fields["groep"] = {"id": zac_parameters["defaultGroepId"], "naam": fields["groep"]}
    body = zaak_body(zac_parameters, omschrijving=registry.tagged("zac-ongeldig"), **fields)
    refused, created = attempt_zaak(zac, urls["zac"], openzaak_productaanvraag, registry, body)
    assert refused.status_code == HTTPStatus.BAD_REQUEST, describe(refused)
    assert created == []


@pytest.mark.scenario("""
    Given a zaak in ZAC with a toelichting
    When the behandelaar changes the toelichting to one over 1000 characters
    Then ZAC refuses it as a bad request
    And the zaak keeps its toelichting
""")
def test_toelichting_over_1000_characters_is_refused_on_edit(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], registry: ResourceRegistry
) -> None:
    """ZAC answers 400 to a toelichting of 1001 characters and keeps the old one."""
    toelichting = registry.tagged("toelichting")
    zaak = zac_zaak(toelichting=toelichting)
    refused = wijzig_zaak(zac, urls["zac"], zaak, toelichting=TOO_LONG_TOELICHTING)
    assert refused.status_code == HTTPStatus.BAD_REQUEST, describe(refused)
    assert read_zaak(zac, urls["zac"], str(zaak["uuid"]))["toelichting"] == toelichting


@pytest.mark.requires("pabc", "cluster")
@pytest.mark.xdist_group("zac-eigen-zaaktype")
@pytest.mark.scenario("""
    Given a zaaktype without servicenorm, with a doorlooptijd
    When the behandelaar starts a zaak of it in ZAC
    Then the zaak has no streefdatum, and its fatale datum is the startdatum plus the doorlooptijd
    And ZAC refuses a streefdatum when a zaak of it is started or changed
""")
def test_zaaktype_without_servicenorm_gives_no_streefdatum(
    zac: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    zac_eigen_zaaktype: JsonObject,
    zac_eigen_zaak: Callable[[], JsonObject],
    registry: ResourceRegistry,
) -> None:
    """einddatumGepland stays empty and is refused with 400 on create and edit; the fatale datum follows doorlooptijd."""
    zaaktype = openzaak.get(f"{CATALOGI}/zaaktypen/{section(zac_eigen_zaaktype, 'zaaktype')['uuid']}")
    assert zaaktype.get("servicenorm") is None
    zaak = zac_eigen_zaak()
    assert zaak.get("einddatumGepland") is None
    assert zaak["uiterlijkeEinddatumAfdoening"] == after_period(str(zaak["startdatum"]), str(zaaktype["doorlooptijd"]))

    streefdatum = (date.fromisoformat(str(zaak["startdatum"])) + timedelta(days=1)).isoformat()
    body = zaak_body(zac_eigen_zaaktype, omschrijving=registry.tagged("zac-streefdatum"), einddatumGepland=streefdatum)
    refused, created = attempt_zaak(zac, urls["zac"], openzaak, registry, body)
    assert refused.status_code == HTTPStatus.BAD_REQUEST, describe(refused)
    assert created == []
    refused = wijzig_zaak(zac, urls["zac"], zaak, einddatumGepland=streefdatum)
    assert refused.status_code == HTTPStatus.BAD_REQUEST, describe(refused)
    assert read_zaak(zac, urls["zac"], str(zaak["uuid"])).get("einddatumGepland") is None


@pytest.mark.scenario("""
    Given ZAC's referentietabel of communicatiekanalen
    When the behandelaar starts or edits a zaak
    Then ZAC offers every communicatiekanaal of the referentietabel but E-formulier
    And a zaak whose communicatiekanaal ZAC no longer offers can be given one it does
""")
def test_communicatiekanalen_offered_are_the_referentietabel_but_e_formulier(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """The offered list is the referentietabel without E-formulier; a zaak with an unlisted kanaal takes a listed one."""
    alle = communicatiekanalen(zac, urls["zac"], inbox=True)
    offered = communicatiekanalen(zac, urls["zac"])
    assert E_FORMULIER in alle
    assert sorted(offered) == sorted(kanaal for kanaal in alle if kanaal != E_FORMULIER)

    zaak = zac_zaak(communicatiekanaal=E_FORMULIER)
    expect_status(wijzig_zaak(zac, urls["zac"], zaak, communicatiekanaal=offered[0]), HTTPStatus.OK)
    assert read_zaak(zac, urls["zac"], str(zaak["uuid"]))["communicatiekanaal"] == offered[0]
