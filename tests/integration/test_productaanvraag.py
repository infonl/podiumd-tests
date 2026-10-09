"""Chain: a productaanvraag in Objecten becomes a zaak through Open Notificaties and ZAC.

Merged from MK and PI test_productaanvraag_flow.py. It uses the environment's own wiring:
the Productaanvraag-Dimpact objecttype, the objecten kanaal and ZAC's zaakafhandelparameters
for profile settings productaanvraag_type and productaanvraag_zaaktype.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.mailpit import received
from podiumd_tests.seed.objecten import make_productaanvraag
from podiumd_tests.seed.openklant import make_submission_contact
from podiumd_tests.zac import PRODUCTAANVRAAG_TIMEOUT
from podiumd_tests.zac import productaanvraag_zaak

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.core,
    pytest.mark.requires("cluster", "objecten", "opennotificaties", "zac", "openzaak"),
]


def test_productaanvraag_becomes_a_zaak(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    objecten: ApiClient,
    openzaak_productaanvraag: ApiClient,
    registry: ResourceRegistry,
    productaanvraagtype: str,
    productaanvraag_objecttype: str,
) -> None:
    """ZAC starts a zaak for a new productaanvraag object and names its kenmerk in the toelichting."""
    kenmerk = registry.tagged("productaanvraag")
    make_productaanvraag(objecten, registry, productaanvraag_objecttype, productaanvraagtype, kenmerk)
    productaanvraag_zaak(openzaak_productaanvraag, registry, kenmerk)


@pytest.mark.tc("OF-002")
@pytest.mark.requires("openklant", "mailpit", "keycloak")
@pytest.mark.usefixtures("ontvangstbevestiging")
def test_zac_mails_the_initiator_an_ontvangstbevestiging(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    podiumd_env: Environment,
    objecten: ApiClient,
    openzaak_productaanvraag: ApiClient,
    openklant: ApiClient,
    mailpit: ApiClient,
    registry: ResourceRegistry,
    productaanvraagtype: str,
    productaanvraag_objecttype: str,
) -> None:
    """ZAC mails the zaaknummer to the e-mail address the form's submitter left in Open Klant."""
    kenmerk = registry.tagged("bevestigd")
    adres = f"{kenmerk}@example.invalid"
    make_submission_contact(openklant, registry, kenmerk, adres)
    make_productaanvraag(objecten, registry, productaanvraag_objecttype, productaanvraagtype, kenmerk)
    zaak = productaanvraag_zaak(openzaak_productaanvraag, registry, kenmerk)
    assert str(zaak["identificatie"]) in received(mailpit, registry, timeout=PRODUCTAANVRAAG_TIMEOUT, to=adres)
