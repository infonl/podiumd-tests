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
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import REFUSED
from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.openzaak import BSN_FILTER
from podiumd_tests.seed.openzaak import DOCUMENTEN
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import link_document
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import make_rol
from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openzaak")]


@pytest.mark.source(
    "TA regression/13-va-filter-cross-component.spec.ts",
    "A zaakvertrouwelijke zaak made by ZAC must not be visible to an application with maximum vertrouwelijkheid openbaar.",
)
@pytest.mark.source(
    "TA regression/23-va-escalatie.spec.ts",
    "An application with maximum vertrouwelijkheid openbaar may never write or read above that level.",
)
@pytest.mark.core
@pytest.mark.scenario("""
    Given a zaakvertrouwelijke zaak in Open Zaak with an initiator's BSN
    When an API client with maximum vertrouwelijkheid openbaar searches and reads the zaak
    Then the search by the initiator's BSN finds no zaak
    And reading the zaak is refused
    But the API client that made the zaak finds it
""")
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


@pytest.mark.source(
    "TA regression/17-document-va-handhaving.spec.ts",
    "A vertrouwelijk document must not be readable by an application with maximum vertrouwelijkheid openbaar.",
)
@pytest.mark.scenario("""
    Given a vertrouwelijk informatieobject in Open Zaak
    When an API client with maximum vertrouwelijkheid openbaar lists and reads informatieobjecten
    Then the list does not contain the informatieobject
    And reading it is refused
    But the API client that made it finds it in the list
""")
def test_vertrouwelijk_document_is_hidden_from_an_openbaar_client(
    openzaak: ApiClient, openzaak_openbaar: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """The openbaar client neither lists nor reads a vertrouwelijk document (TA reg-17)."""
    document = make_document(
        openzaak, registry, parts.informatieobjecttype, vertrouwelijkheidaanduiding="vertrouwelijk"
    )
    # Not titel: every document of a run has the same one. Compare URLs: Open Zaak can give a parallel worker's
    # document the same identificatie.
    own = {"identificatie": str(document["identificatie"])}
    assert document["url"] not in [
        d["url"] for d in openzaak_openbaar.list(f"{DOCUMENTEN}/enkelvoudiginformatieobjecten", own)
    ]
    assert document["url"] in [d["url"] for d in openzaak.list(f"{DOCUMENTEN}/enkelvoudiginformatieobjecten", own)]
    openzaak_openbaar.request("GET", str(document["url"]), *REFUSED, 404)


@pytest.mark.source(
    "TA regression/23-va-escalatie.spec.ts",
    "An application with maximum vertrouwelijkheid openbaar may never write or read above that level.",
)
@pytest.mark.scenario("""
    Given an API client with maximum vertrouwelijkheid openbaar
    When it creates a zaakvertrouwelijke zaak and a vertrouwelijk informatieobject in Open Zaak
    Then Open Zaak refuses both
""")
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


@pytest.mark.source("podiumd-tests", "Checks that a client without zaken.verwijderen cannot delete a zaak.")
@pytest.mark.scenario("""
    Given a zaak in Open Zaak
    When an API client without the right to delete zaken deletes it
    Then Open Zaak refuses the delete
""")
def test_openbaar_client_cannot_delete(
    openzaak: ApiClient, openzaak_openbaar: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """Without zaken.verwijderen a DELETE is refused."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    openzaak_openbaar.request("DELETE", str(zaak["url"]), *REFUSED)


@pytest.mark.source(
    "TA regression/22-negative-auth.spec.ts",
    "Open Zaak refuses expired tokens, unknown clients and applications without autorisaties.",
)
@pytest.mark.parametrize(
    "token",
    [
        pytest.param(lambda secret: zgw_jwt(ZGW_CLIENT_ID, secret, issued_at=int(time.time()) - 7200), id="expired"),
        pytest.param(lambda secret: zgw_jwt("ptest-unknown-client", secret), id="unknown-client"),
    ],
)
@pytest.mark.scenario("""
    Given a token that is expired or names an unknown API client
    When the token is used to list the zaken in Open Zaak
    Then Open Zaak refuses the request
""")
def test_bad_tokens_are_refused(openzaak: ApiClient, zgw_secret: str, token: Callable[[str], str]) -> None:
    """An expired token or an unknown client gets 401/403 (TA reg-22a, c; b: smoke test_bad_token_is_refused)."""
    headers = zgw_headers(token(zgw_secret))
    response = openzaak.http.get(openzaak.url(f"{ZAKEN}/zaken"), headers=headers)
    assert response.status_code in REFUSED, response.status_code


@pytest.mark.source(
    "TA regression/22-negative-auth.spec.ts",
    "Open Zaak refuses expired tokens, unknown clients and applications without autorisaties.",
)
@pytest.mark.scenario("""
    Given an API client that Open Zaak knows, without autorisaties
    When it lists the zaken and creates a zaak
    Then the list is refused or empty
    And creating the zaak is refused
""")
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


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW features, CHECK expand",
    "expand shows no object the token may not read: Open Zaak 1.29.3 fixed expand showing them.",
)
@pytest.mark.scenario("""
    Given an openbaar zaak with an openbaar and a vertrouwelijk document
    When the openbaar client reads the zaak with its document links expanded
    Then the expanded links name only the documents that client may list
""")
def test_expand_shows_no_more_than_the_client_may_list(
    openzaak: ApiClient, openzaak_openbaar: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """expand=zaakinformatieobjecten as the openbaar client shows the same links as its own list of them."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    for vertrouwelijkheid in ("openbaar", "vertrouwelijk"):
        document = make_document(
            openzaak, registry, parts.informatieobjecttype, vertrouwelijkheidaanduiding=vertrouwelijkheid
        )
        link_document(openzaak, registry, zaak, document)
    expanded = openzaak_openbaar.get(str(zaak["url"]), {"expand": "zaakinformatieobjecten"})
    shown = {str(z["informatieobject"]) for z in entries(section(expanded, "_expand").get("zaakinformatieobjecten"))}
    listed = openzaak_openbaar.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": str(zaak["url"])})
    assert shown == {str(z["informatieobject"]) for z in listed}
