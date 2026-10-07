"""Open Zaak autorisaties: vertrouwelijkheid filtering, token checks and a client without rights.

Ported from TA regression 13, 17, 22 and 23. The writer is the suite's own client; the
reader ptest-bootstrap-zgw-openbaar may see vertrouwelijkheid openbaar at most.
"""

from __future__ import annotations

import time

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.zgw_jwt import zgw_headers
from podiumd_tests.auth.zgw_jwt import zgw_jwt
from podiumd_tests.bootstrap.names import ZGW_CLIENT_ID
from podiumd_tests.responses import REFUSED
from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.openzaak import DOCUMENTEN
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import make_rol
from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openzaak")]

BSN_FILTER = "rol__betrokkeneIdentificatie__natuurlijkPersoon__inpBsn"


@pytest.mark.core
def test_zaakvertrouwelijke_zaak_is_hidden_from_an_openbaar_client(
    openzaak: ApiClient, openzaak_openbaar: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """The openbaar client neither lists nor reads a zaakvertrouwelijke zaak; the writer does (TA reg-13, 23b)."""
    bsn = random_bsn()
    zaak = make_zaak(openzaak, registry, parts.zaaktype, vertrouwelijkheidaanduiding="zaakvertrouwelijk")
    make_rol(openzaak, registry, zaak, parts.roltypen["initiator"], inpBsn=bsn)
    assert openzaak_openbaar.list(f"{ZAKEN}/zaken", {BSN_FILTER: bsn}) == []
    assert [z["url"] for z in openzaak.list(f"{ZAKEN}/zaken", {BSN_FILTER: bsn})] == [zaak["url"]]
    openzaak_openbaar.request("GET", str(zaak["url"]), *REFUSED, 404)


def test_vertrouwelijk_document_is_hidden_from_an_openbaar_client(
    openzaak: ApiClient, openzaak_openbaar: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """The openbaar client neither lists nor reads a vertrouwelijk document (TA reg-17)."""
    document = make_document(
        openzaak, registry, parts.informatieobjecttype, vertrouwelijkheidaanduiding="vertrouwelijk"
    )
    titel = {"titel": str(document["titel"])}
    assert openzaak_openbaar.list(f"{DOCUMENTEN}/enkelvoudiginformatieobjecten", titel) == []
    assert [d["url"] for d in openzaak.list(f"{DOCUMENTEN}/enkelvoudiginformatieobjecten", titel)] == [document["url"]]
    openzaak_openbaar.request("GET", str(document["url"]), *REFUSED, 404)


def test_openbaar_client_cannot_create_above_its_level(
    openzaak_openbaar: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """Creating a zaakvertrouwelijke zaak or a vertrouwelijk document is refused (TA reg-23a, 23c)."""
    zaak = {
        "bronorganisatie": "000000000",
        "verantwoordelijkeOrganisatie": "000000000",
        "zaaktype": parts.zaaktype,
        "startdatum": "2026-01-01",
        "omschrijving": registry.tagged("zaak"),
        "vertrouwelijkheidaanduiding": "zaakvertrouwelijk",
    }
    openzaak_openbaar.request("POST", f"{ZAKEN}/zaken", 400, *REFUSED, json=zaak)
    document = {
        "bronorganisatie": "000000000",
        "creatiedatum": "2026-01-01",
        "titel": registry.tagged("document"),
        "auteur": "podiumd-tests",
        "taal": "dut",
        "informatieobjecttype": parts.informatieobjecttype,
        "vertrouwelijkheidaanduiding": "vertrouwelijk",
    }
    openzaak_openbaar.request("POST", f"{DOCUMENTEN}/enkelvoudiginformatieobjecten", 400, *REFUSED, json=document)


def test_openbaar_client_cannot_delete(
    openzaak: ApiClient, openzaak_openbaar: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """Without zaken.verwijderen a DELETE is refused."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    openzaak_openbaar.request("DELETE", str(zaak["url"]), *REFUSED)


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(lambda secret: zgw_jwt(ZGW_CLIENT_ID, secret, issued_at=int(time.time()) - 7200), id="expired"),
        pytest.param(lambda _secret: zgw_jwt(ZGW_CLIENT_ID, "ptest-wrong-secret"), id="wrong-secret"),
        pytest.param(lambda secret: zgw_jwt("ptest-unknown-client", secret), id="unknown-client"),
    ],
)
def test_bad_tokens_are_refused(openzaak: ApiClient, zgw_secret: str, token: Callable[[str], str]) -> None:
    """An expired token, a wrong signature or an unknown client get 401/403 (TA reg-22a-c)."""
    headers = zgw_headers(token(zgw_secret))
    response = openzaak.http.get(openzaak.url(f"{ZAKEN}/zaken"), headers=headers)
    assert response.status_code in REFUSED, response.status_code


def test_client_without_autorisaties(
    openzaak_noauth: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """A known client without autorisaties sees no zaken and cannot create one (TA reg-22d)."""
    response = openzaak_noauth.request("GET", f"{ZAKEN}/zaken", 200, *REFUSED)
    if response.status_code == 200:
        assert response.json()["results"] == []
    zaak = {
        "bronorganisatie": "000000000",
        "verantwoordelijkeOrganisatie": "000000000",
        "zaaktype": parts.zaaktype,
        "startdatum": "2026-01-01",
        "omschrijving": registry.tagged("zaak"),
    }
    openzaak_noauth.request("POST", f"{ZAKEN}/zaken", 403, json=zaak)
