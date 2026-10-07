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


def brp_personen(http: requests.Session, proxy_url: str, query: Mapping[str, object]) -> requests.Response:
    """POST a Haal Centraal personen query (type, burgerservicenummer or search fields, fields)."""
    return http.post(proxy_url + BRP_PERSONEN, json=query)
