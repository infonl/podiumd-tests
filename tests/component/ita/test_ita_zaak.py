"""ITA as the klantcontactmedewerker: a zaak linked to a contactverzoek (Zaak koppelen) and ITA's logboek of it."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ITA_GROEP
from podiumd_tests.ita import answer_body
from podiumd_tests.ita import assign_to_me
from podiumd_tests.ita import close_with_klantcontact
from podiumd_tests.ita import koppel_zaak
from podiumd_tests.ita import logboek
from podiumd_tests.ita import make_contactverzoek
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kcc import expect_ita_group_access_bug
from podiumd_tests.kcc import ita_detail_text
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openklant import ZAAK
from podiumd_tests.seed.openklant import klantcontact_body
from podiumd_tests.seed.openklant import make_actor
from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.requires("ita", "openklant", "openzaak", "keycloak")]

ITA_E2E = "upstream interne-taak-afhandeling/ITA InterneTaakAfhandeling.EndToEndTest/Contactverzoek"


@pytest.fixture(name="groep_taak")
def fixture_groep_taak(
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    logboek_type: str,
    need_bootstrap: Callable[..., None],
    request: pytest.FixtureRequest,
    podiumd_env: Environment,
) -> JsonObject:
    """Return an internetaak assigned to the KCC user's groep, whose detail the user may open."""
    expect_ita_group_access_bug(request, podiumd_env)
    need_bootstrap("objecten-medewerker-kcc")
    groep = make_actor(openklant, registry, "organisatorische_eenheid", ITA_GROEP, "grp")
    return make_contactverzoek(openklant, objecten, registry, logboek_type, [groep])


def _zaken_of(openklant: ApiClient, taak: JsonObject) -> list[str]:
    """The zaak uuids the internetaak's klantcontact is about, from its onderwerpobjecten in Open Klant."""
    klantcontact = openklant.get(
        str(section(taak, "aanleidinggevendKlantcontact")["url"]), {"expand": "gingOverOnderwerpobjecten"}
    )
    identificatoren = [
        section(o, "onderwerpobjectidentificator")
        for o in entries(section(klantcontact, "_expand").get("gingOverOnderwerpobjecten"))
    ]
    codes = list(ZAAK)
    return [
        str(i.get("objectId"))
        for i in identificatoren
        if [i.get("codeObjecttype"), i.get("codeRegister"), i.get("codeSoortObjectId")] == codes
    ]


@pytest.mark.source(
    f"{ITA_E2E}/ContactverzoekScenarios.cs",
    "A zaak is linked to a contactverzoek by its zaaknummer; an unknown one is refused; a second zaak replaces the first.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    And a contactverzoek and two zaken
    When the medewerker links the first zaak by its zaaknummer
    Then the contactverzoek's klantcontact is about that zaak, and its detail shows the zaaknummer
    When the medewerker links the second zaak
    Then the second zaak replaces the first
    And an unknown zaaknummer is refused and changes nothing
""")
def test_zaak_is_linked_and_replaced_by_zaaknummer(  # fixtures
    ita: requests.Session,
    urls: dict[str, str],
    openklant: ApiClient,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    groep_taak: JsonObject,
) -> None:
    """koppel-zaak creates the zgw-Zaak onderwerpobject, then updates it to the second zaak; 404 for an unknown one."""
    taak = groep_taak
    eerste, tweede = (make_zaak(openzaak, registry, parts.zaaktype) for _ in range(2))
    expect_status(koppel_zaak(ita, urls["ita"], taak, str(eerste["identificatie"])), HTTPStatus.OK)
    assert _zaken_of(openklant, taak) == [eerste["uuid"]]
    assert str(eerste["identificatie"]) in ita_detail_text(ita, urls["ita"], taak)
    expect_status(koppel_zaak(ita, urls["ita"], taak, str(tweede["identificatie"])), HTTPStatus.OK)
    assert _zaken_of(openklant, taak) == [tweede["uuid"]]
    unknown = koppel_zaak(ita, urls["ita"], taak, registry.tagged("zaak-bestaat-niet"))
    expect_status(unknown, HTTPStatus.NOT_FOUND)
    assert _zaken_of(openklant, taak) == [tweede["uuid"]]


@pytest.mark.source(
    f"{ITA_E2E}/ContactverzoekScenarios.cs",
    "The logboek shows assigning, linking a zaak, replacing it, a contactmoment and closing.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    And a contactverzoek and two zaken
    When the medewerker assigns it to themselves, links a zaak, replaces it, and closes it with a contactmoment
    Then ITA's logboek of the contactverzoek lists each of those actions
""")
def test_logboek_lists_each_action(  # fixtures
    ita: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    internetaak: JsonObject,
) -> None:
    """The activiteit types of /logboek after toewijzen, koppelen, wijzigen and close-with-klantcontact."""
    assign_to_me(ita, urls["ita"], internetaak)
    for _ in range(2):
        zaak = make_zaak(openzaak, registry, parts.zaaktype)
        expect_status(koppel_zaak(ita, urls["ita"], internetaak, str(zaak["identificatie"])), HTTPStatus.OK)
    close_with_klantcontact(ita, urls["ita"], answer_body(internetaak, klantcontact_body(registry)))
    types = [str(activiteit.get("type")) for activiteit in logboek(ita, urls["ita"], internetaak)]
    assert types == ["verwerkt", "klantcontact", "zaakkoppeling-gewijzigd", "zaak-gekoppeld", "toegewezen"]
