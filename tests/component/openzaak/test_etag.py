"""Open Zaak ETags: a conditional read answers 304 only while the resource is unchanged.

Clients that cache (ZAC, KISS) re-read a zaak with If-None-Match; a stale ETag shows them old data.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import make_rol
from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("openzaak"),
    pytest.mark.source(
        "external OneGround/ZGW-APIs-postman-tests ZGW features, ZRC and DRC ETag",
        "GET and HEAD give an ETag; If-None-Match answers 304 while unchanged; a change gives a new ETag.",
    ),
]


def etag(openzaak: ApiClient, url: str, method: str = "GET") -> str:
    """The resource's current ETag."""
    response = openzaak.request(method, url, HTTPStatus.OK)
    assert response.headers.get("ETag"), f"{method} {url} has no ETag"
    return response.headers["ETag"]


def is_unchanged(openzaak: ApiClient, url: str, tag: str) -> bool:
    """Whether a GET with If-None-Match answers 304."""
    response = openzaak.http.get(openzaak.url(url), headers={**openzaak.headers(), "If-None-Match": tag})
    return response.status_code == HTTPStatus.NOT_MODIFIED


STALE = pytest.mark.xfail(
    strict=True,
    reason="[open-zaak-11] Open Zaak 1.29.3 keeps a zaak's stored ETag after a PATCH or a change of its rollen, so "
    "If-None-Match answers 304 for a changed zaak; probably fixed in 1.31.1 (open-zaak#2577)",
)


@STALE
@pytest.mark.scenario("""
    Given a zaak in Open Zaak
    Then reading it again with its ETag says it did not change
    And after a change, the old ETag no longer matches
""")
def test_zaak_etag_follows_a_patch(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """A zaak's ETag: 304 while unchanged, no longer after a PATCH."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    url = str(zaak["url"])
    tag = etag(openzaak, url)
    assert is_unchanged(openzaak, url, tag)
    openzaak.patch(url, {"toelichting": registry.tagged("etag")})
    assert not is_unchanged(openzaak, url, tag), "a PATCH kept the zaak's ETag"


@pytest.mark.scenario("""
    Given a document in Open Zaak
    Then reading it again with its ETag says it did not change
    And after a change, the old ETag no longer matches
""")
def test_document_etag_follows_a_change(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """A document's ETag (HEAD): 304 while unchanged, no longer after a PATCH."""
    document = make_document(openzaak, registry, parts.informatieobjecttype)
    url = str(document["url"])
    tag = etag(openzaak, url, "HEAD")
    assert is_unchanged(openzaak, url, tag)
    lock = openzaak.request("POST", f"{url}/lock", HTTPStatus.OK, json={}).json()["lock"]
    openzaak.request("PATCH", url, HTTPStatus.OK, json={"titel": registry.tagged("etag"), "lock": lock})
    openzaak.request("POST", f"{url}/unlock", HTTPStatus.NO_CONTENT, json={"lock": lock})
    assert not is_unchanged(openzaak, url, tag), "a PATCH kept the document's ETag"


@STALE
@pytest.mark.scenario("""
    Given a zaak in Open Zaak
    When a rol is added to it, and when that rol is deleted again
    Then each time the zaak's old ETag no longer matches, since the zaak lists its rollen
""")
def test_zaak_etag_follows_its_rollen(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """Adding or deleting a rol changes the zaak's ETag: the zaak's rollen field changes."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    url = str(zaak["url"])
    before = etag(openzaak, url)
    rol = make_rol(openzaak, registry, zaak, parts.roltypen["initiator"], inpBsn="999990019")
    assert not is_unchanged(openzaak, url, before), "adding a rol kept the zaak's ETag"
    with_rol = etag(openzaak, url)
    openzaak.delete(str(rol["url"]))
    assert not is_unchanged(openzaak, url, with_rol), "deleting a rol kept the zaak's ETag"
