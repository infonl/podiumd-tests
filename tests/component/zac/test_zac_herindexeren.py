"""ZAC's full reindex of zaken in its Solr index.

Destructive: ZAC empties its index of zaken first, so every other test's search misses zaken until it ends.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.responses import describe
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.zac import is_zaak_listed
from podiumd_tests.zac import reindex_zaken

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.destructive,
    # cluster: the reindex is called inside ZAC's pod.
    pytest.mark.requires("zac", "openzaak", "keycloak", "pabc", "cluster"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md,"
        " zoeken-werklijsten-dashboard): the reindex skips a zaak it cannot read.",
    ),
]

# ZAC 5.9.1 reads only a Point as zaakgeometrie (GeoJSONGeometry.coordinates).
VLAK = {"type": "Polygon", "coordinates": [[[4.88, 52.37], [4.9, 52.37], [4.9, 52.38], [4.88, 52.37]]]}
PUNT = {"type": "Point", "coordinates": [4.89316, 52.36673]}
# ZAC's error code for a zaak whose zaakgeometrie it cannot read (RestExceptionMapper).
GEOMETRIE_NOT_SUPPORTED = "msg.error.zaak.geometrie.not-supported"


@pytest.mark.scenario("""
    Given a zaak with a point and a zaak with a polygon as location, of the BPMN test zaaktype
    When ZAC reindexes all zaken
    Then the reindex ends and ZAC's search finds the zaak with the point
    And not the zaak with the polygon
    And opening the zaak with the polygon gives a message that its location type is not supported
""")
def test_reindex_skips_a_zaak_whose_geometrie_zac_cannot_read(
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    bpmn_zaaktype: JsonObject,
    registry: ResourceRegistry,
) -> None:
    """The reindex converts each zaak on its own: a Polygon zaakgeometrie skips that zaak only."""
    zaaktype = str(bpmn_zaaktype["url"])
    punt = make_zaak(openzaak, registry, zaaktype, zaakgeometrie=PUNT)
    vlak = make_zaak(openzaak, registry, zaaktype, zaakgeometrie=VLAK)
    reindex_zaken(podiumd_env)
    assert is_zaak_listed(zac, urls["zac"], punt)
    assert not is_zaak_listed(zac, urls["zac"], vlak)
    refused = zac.get(f"{urls['zac']}/rest/zaken/zaak/{vlak['uuid']}")
    assert refused.status_code == HTTPStatus.BAD_REQUEST, describe(refused)
    assert GEOMETRIE_NOT_SUPPORTED in refused.text
