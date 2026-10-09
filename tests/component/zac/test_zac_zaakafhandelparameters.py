"""ZAC can start zaken of the zaaktype it handles productaanvragen for.

Ported from PI test_zac_zaakafhandelparameters.py: a zaaktype published in Open Zaak is unusable
in ZAC until ZAC's own zaakafhandelparameters for it are valide (a group, a case definition and a
"niet ontvankelijk" resultaattype). The zaaktype is the profile setting productaanvraag_zaaktype.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.zac import zaakafhandelparameters

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "openzaak", "keycloak")]


def test_zaakafhandelparameters_are_valide(
    zac: requests.Session, urls: dict[str, str], openzaak: ApiClient, podiumd_env: Environment
) -> None:
    """ZAC reports its zaakafhandelparameters for the productaanvraag zaaktype as valide (PI)."""
    identificatie = podiumd_env.profile.settings.get("productaanvraag_zaaktype")
    if not identificatie:
        pytest.skip(f"profile {podiumd_env.profile.name} has no settings.productaanvraag_zaaktype")
    zaaktypen = openzaak.list(f"{CATALOGI}/zaaktypen", {"identificatie": identificatie, "status": "definitief"})
    assert zaaktypen, f"no published zaaktype {identificatie} in Open Zaak"
    for zaaktype in zaaktypen:
        url = f"{urls['zac']}/rest/zaakafhandelparameters/{str(zaaktype['url']).rsplit('/', 1)[-1]}"
        assert expect_status(zac.get(url), HTTPStatus.OK).json()["valide"], zaaktype["url"]


def test_handled_zaaktypen_pass_zacs_inrichtingscheck(zac: requests.Session, urls: dict[str, str]) -> None:
    """Every zaaktype ZAC has zaakafhandelparameters for passes ZAC's own inrichtingscheck (Admin, Inrichtingscheck).

    The check covers what ZAC needs of a zaaktype in Open Zaak, e.g. an informatieobjecttype "e-mail",
    without which ZAC fails after sending a mail when it stores the mail with the zaak.
    """
    handled = {section(p, "zaaktype").get("identificatie") for p in zaakafhandelparameters(zac, urls["zac"])}
    checks = entries(expect_status(zac.get(f"{urls['zac']}/rest/health-check/zaaktypes"), HTTPStatus.OK).json())
    failing = {
        str(section(c, "zaaktype").get("identificatie")): sorted(
            k for k, v in c.items() if v is False and k != "valide"
        )
        for c in checks
        if section(c, "zaaktype").get("identificatie") in handled and not c.get("valide")
    }
    assert not failing, f"ZAC's inrichtingscheck fails: {failing}"
