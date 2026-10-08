"""BRP (Haal Centraal personen) and KvK through the environment's api-proxy, as the apps call them."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    import requests

BRP_PERSONEN = "/haalcentraal/api/brp/personen"
KVK_ZOEKEN = "/api/v2/zoeken"
KVK_BASISPROFIELEN = "/api/v1/basisprofielen"
# The KvK API answers HAL; WireMock's KvK mappings match on it.
KVK_HEADERS = {"Accept": "application/hal+json"}
# KvK's public test API (QA's api-proxy target): Test BV Donald, with its hoofdvestiging address.
KVK_TEST_NUMMER = "68750110"
KVK_TEST_ADRES = {"postcode": "8823SJ", "huisnummer": "3"}


def brp_personen(http: requests.Session, proxy_url: str, query: Mapping[str, object]) -> requests.Response:
    """POST a Haal Centraal personen query (type, burgerservicenummer or search fields, fields)."""
    return http.post(proxy_url + BRP_PERSONEN, json=query)


def kvk_zoeken(http: requests.Session, proxy_url: str, query: Mapping[str, str]) -> requests.Response:
    """GET a KvK zoeken query."""
    return http.get(proxy_url + KVK_ZOEKEN, params=query, headers=KVK_HEADERS)
