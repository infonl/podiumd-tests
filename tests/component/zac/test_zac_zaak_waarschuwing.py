"""ZAC's dashboard list of zaken nearing their streefdatum or fatale datum (card Mijn zaken met waarschuwing)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.seed.openzaak import make_rol
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.openzaak import today
from podiumd_tests.seed.zac_zaaktype import make_group_member
from podiumd_tests.seed.zac_zaaktype import make_role_group
from podiumd_tests.seed.zac_zaaktype import make_zac_zaaktype
from podiumd_tests.seed.zac_zaaktype import zac_as_admin
from podiumd_tests.zac import clean_up_zaak
from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import save_zaakafhandelparameters
from podiumd_tests.zac import zac_session
from podiumd_tests.zac_signaleringen import zaak_waarschuwingen

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    # A throwaway zaaktype is made known to PABC and deleted with a Django snippet.
    pytest.mark.requires("zac", "openzaak", "keycloak", "pabc", "cluster"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md,"
        " zoeken-werklijsten-dashboard): bijna verlopen signal.",
    ),
]


# The venster of each date of a zaak, in its zaakafhandelparameters.
VENSTERS = {
    "einddatumGepland": "einddatumGeplandWaarschuwing",
    "uiterlijkeEinddatumAfdoening": "uiterlijkeEinddatumAfdoeningWaarschuwing",
}


@pytest.mark.scenario("""
    Given a zaaktype with a servicenorm and a doorlooptijd, and no waarschuwingsvenster
    And a zaak of it on the test admin's name
    Then the admin's dashboard does not list the zaak among the zaken with a warning
    When the beheerder sets a streefdatum or fatale datum venster that ends the day before that date
    Then the dashboard does not list the zaak
    When the venster reaches that date
    Then the dashboard lists the zaak
""")
def test_bijna_verlopen_follows_the_waarschuwingsvenster(
    podiumd_env: Environment,
    openzaak: ApiClient,
    test_zaaktype: JsonObject,
    urls: dict[str, str],
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """/rest/zaken/waarschuwing lists an open zaak whose date is at most the venster's days ahead; none without one."""
    need_bootstrap("zac-bpmn-process")
    parameters = make_zac_zaaktype(podiumd_env, openzaak, registry, test_zaaktype, servicenorm="P10D")
    # A login after make_zac_zaaktype: ZAC reads the rights on the zaaktype from PABC at login.
    zac, zac_url = zac_as_admin(podiumd_env), urls["zac"]
    zaak = create_zaak(
        zac, zac_url, parameters, omschrijving=registry.tagged("zac-waarschuwing"), behandelaar={"id": ADMIN.username}
    )
    clean_up_zaak(zac, zac_url, openzaak, registry, zaak)
    assert zaak["identificatie"] not in zaak_waarschuwingen(zac, zac_url)

    for veld, venster in VENSTERS.items():
        # ZAC's today: the zaak's dates follow from its startdatum, today.
        dagen = (date.fromisoformat(str(zaak[veld])) - date.fromisoformat(str(zaak["startdatum"]))).days
        for days, listed in ((dagen - 1, False), (dagen, True)):
            parameters = save_zaakafhandelparameters(
                zac, zac_url, {**parameters, **dict.fromkeys(VENSTERS.values()), venster: days}
            )
            assert (zaak["identificatie"] in zaak_waarschuwingen(zac, zac_url)) == listed, (veld, days)


# Open Zaak's page size: ZAC 5.9.1 reads one page of the user's zaken for the card.
OPEN_ZAAK_PAGE = 100


@pytest.mark.xfail(
    strict=True,
    reason="[zac-33] ZAC 5.9.1's bijna verlopen card reads one page of the user's zaken from Open Zaak (the 100 "
    "newest), so an older zaak in its waarschuwingsvenster is not listed; not yet reported upstream",
)
@pytest.mark.slow
@pytest.mark.destructive
@pytest.mark.scenario("""
    Given a new behandelaar with a zaak inside the zaaktype's fatale datum waarschuwingsvenster
    Then the behandelaar's dashboard lists the zaak among the zaken with a warning
    When 100 newer zaken without a fatale datum are put on the behandelaar's name
    Then the dashboard still lists the zaak among the zaken with a warning
""")
def test_bijna_verlopen_lists_a_zaak_behind_100_newer_ones(
    podiumd_env: Environment,
    openzaak: ApiClient,
    test_zaaktype: JsonObject,
    parts: ZaaktypeParts,
    urls: dict[str, str],
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """/rest/zaken/waarschuwing reads every zaak of the user, not only Open Zaak's first page of the newest."""
    need_bootstrap("zac-bpmn-process")
    parameters = make_zac_zaaktype(podiumd_env, openzaak, registry, test_zaaktype)
    group = make_role_group(podiumd_env, registry, "behandelaar")
    username, password = make_group_member(podiumd_env, registry, group)
    zac, zac_url = zac_as_admin(podiumd_env), urls["zac"]
    zaak = create_zaak(
        zac,
        zac_url,
        parameters,
        omschrijving=registry.tagged("zac-waarschuwing"),
        groep={"id": group, "naam": group},
        behandelaar={"id": username},
    )
    clean_up_zaak(zac, zac_url, openzaak, registry, zaak)
    dagen = (date.fromisoformat(str(zaak["uiterlijkeEinddatumAfdoening"])) - date.fromisoformat(today())).days
    save_zaakafhandelparameters(zac, zac_url, {**parameters, "uiterlijkeEinddatumAfdoeningWaarschuwing": dagen})
    user = zac_session(podiumd_env, username, password)
    assert zaak["identificatie"] in zaak_waarschuwingen(user, zac_url)

    roltype = next(iter(parts.roltypen.values()))
    for _ in range(OPEN_ZAAK_PAGE):
        newer = make_zaak(openzaak, registry, parts.zaaktype)
        make_rol(openzaak, registry, newer, roltype, "medewerker", identificatie=username)
    assert zaak["identificatie"] in zaak_waarschuwingen(user, zac_url)
