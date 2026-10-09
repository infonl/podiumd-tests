"""Chain: a productaanvraag in Objecten becomes a zaak through Open Notificaties and ZAC.

Merged from MK and PI test_productaanvraag_flow.py. It uses the environment's own wiring:
the Productaanvraag-Dimpact objecttype, the objecten kanaal and ZAC's zaakafhandelparameters
for profile settings productaanvraag_type and productaanvraag_zaaktype.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import PRODUCTAANVRAAG_OBJECTTYPE
from podiumd_tests.mailpit import received
from podiumd_tests.seed.objecten import make_productaanvraag
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openklant import FORMULIERINZENDING
from podiumd_tests.seed.openklant import clean_up_klantcontacten
from podiumd_tests.seed.openklant import make_betrokkene
from podiumd_tests.seed.openklant import make_digitaal_adres
from podiumd_tests.seed.openklant import make_klantcontact
from podiumd_tests.seed.openklant import make_onderwerpobject
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.seed.openzaak import today
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import confirmation_on

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.core,
    pytest.mark.requires("cluster", "objecten", "opennotificaties", "zac", "openzaak"),
]

# Objecten notifies, Open Notificaties delivers to ZAC, and ZAC starts the zaak and its case.
ZAAK_TIMEOUT = 120


@pytest.fixture(scope="module", name="productaanvraagtype")
def fixture_productaanvraagtype(podiumd_env: Environment) -> str:
    """The productaanvraagtype ZAC starts a zaak for; skips without the profile setting."""
    found = podiumd_env.profile.settings.get("productaanvraag_type")
    if not found:
        pytest.skip(f"profile {podiumd_env.profile.name} has no settings.productaanvraag_type")
    return found


@pytest.fixture(scope="module", name="objecttype")
def fixture_objecttype(podiumd_env: Environment) -> str:
    """The productaanvraag objecttype's URL as Objecten knows it."""
    return objecttype_url(podiumd_env, PRODUCTAANVRAAG_OBJECTTYPE)


def zaak_for(openzaak_productaanvraag: ApiClient, registry: ResourceRegistry, kenmerk: str) -> JsonObject:
    """The zaak ZAC starts for the productaanvraag, with its kenmerk in the toelichting; cleanup deletes it."""

    def started() -> JsonObject | None:
        zaken = openzaak_productaanvraag.list(f"{ZAKEN}/zaken", {"startdatum": today()})
        return next((z for z in zaken if kenmerk in str(z.get("toelichting") or "")), None)

    zaak = wait_until(started, timeout=ZAAK_TIMEOUT, interval=3, description=f"zaak for productaanvraag {kenmerk}")
    url = str(zaak["url"])
    registry.add(f"zaak {url}", lambda: delete_zaak(openzaak_productaanvraag, url))
    return zaak


def test_productaanvraag_becomes_a_zaak(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    objecten: ApiClient,
    openzaak_productaanvraag: ApiClient,
    registry: ResourceRegistry,
    productaanvraagtype: str,
    objecttype: str,
) -> None:
    """ZAC starts a zaak for a new productaanvraag object and names its kenmerk in the toelichting."""
    kenmerk = registry.tagged("productaanvraag")
    make_productaanvraag(objecten, registry, objecttype, productaanvraagtype, kenmerk)
    zaak_for(openzaak_productaanvraag, registry, kenmerk)


@pytest.mark.tc("OF-002")
@pytest.mark.requires("openklant", "mailpit", "keycloak")
def test_zac_mails_the_initiator_an_ontvangstbevestiging(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    podiumd_env: Environment,
    objecten: ApiClient,
    openzaak_productaanvraag: ApiClient,
    openklant: ApiClient,
    mailpit: ApiClient,
    registry: ResourceRegistry,
    productaanvraagtype: str,
    objecttype: str,
    need_bootstrap: Callable[..., None],
    zac: requests.Session,
) -> None:
    """ZAC mails the zaaknummer to the e-mail address the form's submitter left in Open Klant.

    Open Formulieren's registration of the submitter's contact details: a klantcontact about the
    submission (onderwerpobject with the productaanvraag's kenmerk), with a betrokkene and its address.
    """
    need_bootstrap("zac-email-confirmation")
    zaaktype = str(podiumd_env.profile.settings.get("productaanvraag_zaaktype"))
    if not confirmation_on(zac, podiumd_env.profile.urls["zac"], zaaktype):
        pytest.skip(
            f"ZAC sends no ontvangstbevestiging for {zaaktype}: allow it with profile setting zac_email_confirmation"
        )
    kenmerk = registry.tagged("bevestigd")
    adres = f"{kenmerk}@example.invalid"
    klantcontact = make_klantcontact(openklant, registry, onderwerp=kenmerk)
    betrokkene = make_betrokkene(openklant, registry, klantcontact, None)
    make_digitaal_adres(openklant, registry, None, adres, betrokkene)
    make_onderwerpobject(openklant, registry, klantcontact, kenmerk, FORMULIERINZENDING)
    # ZAC links the zaak to the klantcontact: the whole tree goes first.
    clean_up_klantcontacten(openklant, registry, kenmerk)
    make_productaanvraag(objecten, registry, objecttype, productaanvraagtype, kenmerk)
    zaak = zaak_for(openzaak_productaanvraag, registry, kenmerk)
    assert str(zaak["identificatie"]) in received(mailpit, registry, timeout=ZAAK_TIMEOUT, to=adres)
