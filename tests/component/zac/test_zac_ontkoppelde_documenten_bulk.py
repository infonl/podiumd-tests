"""ZAC's ontkoppelde documenten deleted or linked in bulk, from ZAC 5.12.0 (#7739)."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import DOCUMENTEN
from podiumd_tests.workloads import skip_older_than
from podiumd_tests.zac_documents import bulk_ontkoppelde_documenten
from podiumd_tests.zac_documents import document_url
from podiumd_tests.zac_documents import ontkoppel_document
from podiumd_tests.zac_documents import ontkoppeld_entry
from podiumd_tests.zac_documents import uploaded_document
from podiumd_tests.zac_documents import zaak_documents

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "openzaak", "keycloak"),
    pytest.mark.source(
        "PZW Sprint 83 PZ-10331",
        "Ontkoppelde documenten are deleted or linked in bulk; a document that cannot be is reported, the others are done.",
    ),
]

# The release that deletes and links ontkoppelde documenten in bulk (#7739).
BULK = (5, 12, 0)
REDEN = "podiumd-tests bulk"


def _detached(
    zac: requests.Session, zac_url: str, zaak: JsonObject, registry: ResourceRegistry
) -> tuple[JsonObject, JsonObject]:
    """A new document of the zaak, detached from it: the document and its ontkoppelde documenten entry."""
    document = uploaded_document(zac, zac_url, zaak, registry)
    expect_status(ontkoppel_document(zac, zac_url, zaak, document, REDEN, registry), HTTPStatus.NO_CONTENT)
    entry = ontkoppeld_entry(zac, zac_url, zaak, document)
    assert entry, f"{document['uuid']} not in the ontkoppelde documenten of {zaak['identificatie']}"
    return document, entry


@pytest.mark.scenario("""
    Given three documents detached from a zaak, one of them locked
    When the beheerder deletes the three from the ontkoppelde documenten at once
    Then ZAC deletes the two unlocked ones, from its ontkoppelde documenten and from Open Zaak
    And reports the locked one as not deleted, because it is vergrendeld
""")
def test_ontkoppelde_documenten_are_deleted_in_bulk_but_a_locked_one(  # the zaak and Open Zaak
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    openzaak_productaanvraag: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """lijst/verwijderen deletes every id it can and names the locked one VERGRENDELD."""
    skip_older_than(podiumd_env, "zac", BULK, "no bulk actions on ontkoppelde documenten")
    zac_url = urls["zac"]
    zaak = zac_zaak()
    free = [_detached(zac, zac_url, zaak, registry) for _ in range(2)]
    locked_document = uploaded_document(zac, zac_url, zaak, registry, status="in_bewerking")
    url = document_url(zac_url, locked_document)
    expect_status(zac.post(f"{url}/lock", params={"zaak": str(zaak["uuid"])}), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    expect_status(ontkoppel_document(zac, zac_url, zaak, locked_document, REDEN, registry), HTTPStatus.NO_CONTENT)
    # Unlocked before the cleanup of ontkoppel_document deletes it.
    registry.add(f"lock of document {locked_document['uuid']}", lambda: zac.post(f"{url}/unlock"))
    locked = ontkoppeld_entry(zac, zac_url, zaak, locked_document)
    assert locked

    result = bulk_ontkoppelde_documenten(zac, zac_url, "verwijderen", [entry for _, entry in free] + [locked])
    assert sorted(cast("list[int]", result["verwerkt"])) == sorted(int(str(entry["id"])) for _, entry in free)
    assert [(failure.get("id"), failure.get("foutcode")) for failure in entries(result["mislukt"])] == [
        (locked["id"], "VERGRENDELD")
    ]
    assert [ontkoppeld_entry(zac, zac_url, zaak, document) for document, _ in free] == [None, None]
    for document, _ in free:
        gone = f"{urls['openzaak']}/{DOCUMENTEN}/enkelvoudiginformatieobjecten/{document['uuid']}"
        openzaak_productaanvraag.request("GET", gone, HTTPStatus.NOT_FOUND)
    assert ontkoppeld_entry(zac, zac_url, zaak, locked_document)


@pytest.mark.scenario("""
    Given two documents detached from a zaak
    When the behandelaar links the two to another zaak at once
    Then both are documents of the other zaak
    And neither is in the ontkoppelde documenten any more
""")
def test_ontkoppelde_documenten_are_linked_to_a_zaak_in_bulk(
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    registry: ResourceRegistry,
) -> None:
    """lijst/koppelen links every id to the zaak with nieuweZaakID."""
    skip_older_than(podiumd_env, "zac", BULK, "no bulk actions on ontkoppelde documenten")
    zac_url = urls["zac"]
    zaak, other = zac_zaak(), zac_zaak()
    detached = [_detached(zac, zac_url, zaak, registry) for _ in range(2)]

    result = bulk_ontkoppelde_documenten(
        zac, zac_url, "koppelen", [entry for _, entry in detached], nieuweZaakID=other["identificatie"]
    )
    assert (sorted(cast("list[int]", result["verwerkt"])), result["mislukt"]) == (
        sorted(int(str(entry["id"])) for _, entry in detached),
        [],
    )
    linked = {item.get("uuid") for item in zaak_documents(zac, zac_url, other)}
    assert {document["uuid"] for document, _ in detached} <= linked
    assert [ontkoppeld_entry(zac, zac_url, zaak, document) for document, _ in detached] == [None, None]
