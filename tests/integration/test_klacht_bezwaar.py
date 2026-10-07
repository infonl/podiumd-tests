"""Chain: klacht, besluit and bezwaar as related zaken. Ported from TA regression 63."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.openzaak import BSN_FILTER
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import make_besluit
from podiumd_tests.seed.openzaak import make_rol
from podiumd_tests.seed.openzaak import make_status
from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.integration, pytest.mark.requires("openzaak")]


def test_bezwaar_is_a_zaak_about_the_klacht(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """A klacht gets two statussen and a besluit; the bezwaar of the same inwoner refers to it, and _zoek finds both."""
    bsn = random_bsn()
    initiator = parts.roltypen["initiator"]
    klacht = make_zaak(openzaak, registry, parts.zaaktype)
    make_rol(openzaak, registry, klacht, initiator, inpBsn=bsn)
    for statustype in parts.statustypen[:2]:
        make_status(openzaak, klacht, str(statustype["url"]))
    make_besluit(openzaak, registry, parts.besluittype, zaak=klacht["url"])

    bezwaar = make_zaak(openzaak, registry, parts.zaaktype, toelichting=f"Bezwaar tegen {klacht['identificatie']}")
    make_rol(openzaak, registry, bezwaar, initiator, inpBsn=bsn)
    openzaak.patch(str(bezwaar["url"]), {"relevanteAndereZaken": [{"url": klacht["url"], "aardRelatie": "onderwerp"}]})

    relaties = entries(openzaak.get(str(bezwaar["url"]))["relevanteAndereZaken"])
    assert [(r["url"], r["aardRelatie"]) for r in relaties] == [(klacht["url"], "onderwerp")]
    assert len(openzaak.list(f"{ZAKEN}/statussen", {"zaak": str(klacht["url"])})) == len(parts.statustypen[:2])
    zoek = openzaak.request("POST", f"{ZAKEN}/zaken/_zoek", 200, json={BSN_FILTER: bsn}).json()
    assert {z["url"] for z in entries(zoek["results"])} == {klacht["url"], bezwaar["url"]}
