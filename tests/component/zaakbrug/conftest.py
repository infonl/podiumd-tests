"""Fixtures for ZaakBrug: the run's first identificaties and a zaak created through ZaakBrug."""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import ZAAKBRUG_ZAAKTYPE
from podiumd_tests.lock import file_lock
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak_at_cleanup
from podiumd_tests.zaakbrug import NO_VELDEN
from podiumd_tests.zaakbrug import ZAAKBRUG_BRONORGANISATIE
from podiumd_tests.zaakbrug import ZDS
from podiumd_tests.zaakbrug import CreatedZaak
from podiumd_tests.zaakbrug import creeer_zaak
from podiumd_tests.zaakbrug import genereer_document_id
from podiumd_tests.zaakbrug import genereer_zaak_id
from podiumd_tests.zaakbrug import is_bevestiging
from podiumd_tests.zaakbrug import send
from podiumd_tests.zaakbrug import zaak_identificatie

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.registry import ResourceRegistry
    from podiumd_tests.zaakbrug import ZaakVelden

INITIATOR_BSN = "111111110"


@pytest.fixture(scope="module", name="first_identificaties")
def fixture_first_identificaties(http: requests.Session, urls: dict[str, str], run_dir: Path) -> None:
    """The run's first genereer calls, one worker at a time: parallel first calls break ZaakBrug's counter (zaakbrug-2)."""
    done = run_dir / "zaakbrug-identificaties"
    with file_lock(run_dir / "zaakbrug-identificaties.lock"):
        if done.exists():
            return
        now, url = datetime.now(UTC), f"{urls['zaakbrug']}{ZDS}/VrijBericht"
        send(http, url, genereer_zaak_id(now), "genereerZaakIdentificatie_Di02")
        send(http, url, genereer_document_id(now), "genereerDocumentIdentificatie_Di02")
        done.touch()


@pytest.fixture(name="zaakbrug_zaak")
def fixture_zaakbrug_zaak(
    http: requests.Session, urls: dict[str, str], openzaak: ApiClient, registry: ResourceRegistry
) -> Callable[..., CreatedZaak]:
    """Create a zaak through genereerZaakIdentificatie and creeerZaak (Bv03); cleanup deletes it with its documents.

    Its initiator is the natuurlijk persoon with INITIATOR_BSN unless bsn is given.
    """

    def create(velden: ZaakVelden = NO_VELDEN, bsn: str = INITIATOR_BSN) -> CreatedZaak:
        now = datetime.now(UTC)
        base = urls["zaakbrug"] + ZDS
        zaak = zaak_identificatie(
            send(http, f"{base}/VrijBericht", genereer_zaak_id(now), "genereerZaakIdentificatie_Di02")
        )
        assert zaak
        envelope = creeer_zaak(now, zaak, ZAAKBRUG_ZAAKTYPE, bsn, velden=velden)
        assert is_bevestiging(send(http, f"{base}/OntvangAsynchroon", envelope, "creeerZaak_Lk01"))
        found = openzaak.list(f"{ZAKEN}/zaken", {"identificatie": zaak, "bronorganisatie": ZAAKBRUG_BRONORGANISATIE})
        assert found, f"no zaak {zaak} in Open Zaak after creeerZaak"
        url = str(found[0]["url"])
        delete_zaak_at_cleanup(openzaak, registry, url, with_documents=True)
        return CreatedZaak(zaak, url)

    return create
